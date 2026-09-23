"""Background monitoring task for active subscriptions."""

import asyncio
import random
import time
import traceback

import discord
from discord.ext import commands, tasks

import config
import data
import scraper
import utils


class Monitor(commands.Cog):
    """Cog managing background polling loops and admin error reporting."""

    def __init__(
        self,
        bot: commands.Bot,
        data_store: data.DataStore | None = None,
    ) -> None:
        """Initializes the monitor cog and starts the polling task.

        Args:
            bot: The commands.Bot instance.
            data_store: Optional custom DataStore instance.
        """
        self.bot = bot
        self.db = data_store or data.get_data_store()
        self.instagram_cooldown_until: float = 0.0
        self.current_instagram_cooldown: float = float(
            config.INSTAGRAM_CHECK_INTERVAL_SECONDS
        )
        self.last_checked_times: dict[tuple[str, str], float] = {}
        self.monitor_loop.start()

    async def cog_unload(self) -> None:
        """Stops the heartbeat loop task when the cog is unloaded."""
        self.monitor_loop.cancel()

    @tasks.loop(seconds=config.HEARTBEAT_DELAY_SECONDS)
    async def monitor_loop(self) -> None:
        """Background monitoring task to poll public Profiles for updates."""
        print("Heartbeat check started.")
        targets = self.db.get_unique_targets()

        for platform, username in sorted(targets):
            try:
                await self._check_profile(username, platform=platform)
            except Exception:  # pylint: disable=broad-except
                error_trace = traceback.format_exc()
                print(f"Error checking updates for @{username}:\n{error_trace}")
                plat_name = platform.capitalize()
                err_label = (
                    f"Error scraping @{username}:\n"
                    if platform == data.Platform.THREADS
                    else f"Error scraping {plat_name} @{username}:\n"
                )
                await self.report_error(
                    f"{err_label}```\n{error_trace[:1800]}\n```"
                )

        print("Heartbeat check done.")
        if config.HEARTBEAT_JITTER_SECONDS > 0:
            jitter = random.uniform(
                -config.HEARTBEAT_JITTER_SECONDS,
                config.HEARTBEAT_JITTER_SECONDS,
            )
            next_interval = max(10.0, config.HEARTBEAT_DELAY_SECONDS + jitter)
            self.monitor_loop.change_interval(seconds=next_interval)

    @monitor_loop.before_loop
    async def before_monitor(self) -> None:
        """Awaits ready state before launching the check loop."""
        await self.bot.wait_until_ready()

    async def _sleep_with_jitter(self) -> None:
        """Sleeps for CHECK_DELAY_SECONDS plus random jitter."""
        jitter = (
            random.uniform(0.0, config.CHECK_JITTER_SECONDS)
            if config.CHECK_JITTER_SECONDS > 0
            else 0.0
        )
        await asyncio.sleep(config.CHECK_DELAY_SECONDS + jitter)

    def _should_skip_instagram(self, username: str) -> bool:
        """Determines if an Instagram profile check should be skipped.

        Checks both the rate-limit cooldown and check interval timers.

        Args:
            username: The Instagram username to check.

        Returns:
            True if the check should be skipped, False otherwise.
        """
        now = time.time()
        if now < self.instagram_cooldown_until:
            remaining = self.instagram_cooldown_until - now
            rem_str = utils.format_duration(remaining)
            print(
                f"[Instagram Anti-Bot] Skipping @{username} "
                f"(rate-limit cooldown, {rem_str} remaining)."
            )
            return True

        last_checked = self.last_checked_times.get(
            (username, data.Platform.INSTAGRAM), 0.0
        )
        elapsed = now - last_checked
        if elapsed < config.INSTAGRAM_CHECK_INTERVAL_SECONDS:
            remaining = config.INSTAGRAM_CHECK_INTERVAL_SECONDS - elapsed
            rem_str = utils.format_duration(remaining)
            print(
                f"[Instagram Interval] Skipping @{username} "
                f"({rem_str} remaining before next check)."
            )
            return True

        self.last_checked_times[(username, data.Platform.INSTAGRAM)] = now
        return False

    async def _handle_instagram_rate_limit(
        self, username: str, exc: Exception
    ) -> None:
        """Handles Instagram rate-limiting with exponential backoff.

        Args:
            username: The profile username that encountered the rate limit.
            exc: The caught rate limit exception.
        """
        effective_cooldown = min(
            self.current_instagram_cooldown,
            float(config.INSTAGRAM_MAX_COOLDOWN_SECONDS),
        )
        self.instagram_cooldown_until = time.time() + effective_cooldown
        cooldown_str = utils.format_duration(effective_cooldown)
        warning_msg = (
            f"[Instagram Anti-Bot] Rate limit / login wall detected "
            f"for @{username}: {exc}. Pausing Instagram checks for "
            f"{cooldown_str}."
        )
        print(warning_msg)
        await self.report_error(f"⚠️ {warning_msg}")
        self.current_instagram_cooldown = min(
            float(config.INSTAGRAM_MAX_COOLDOWN_SECONDS),
            effective_cooldown * 2.0,
        )

    async def _check_profile(
        self,
        username: str,
        platform: str | data.Platform = data.Platform.THREADS,
    ) -> None:
        """Processes a single profile check for new posts.

        Args:
            username: The username profile to check.
            platform: Social platform (Platform.THREADS or Platform.INSTAGRAM).
        """
        if platform == data.Platform.INSTAGRAM and self._should_skip_instagram(
            username
        ):
            return

        print(
            f"Checking updates for {platform.capitalize()} profile: @{username}"
        )
        try:
            posts: list[data.PostDict] = await scraper.scrape_user_posts(
                self.bot.browser, username, platform=platform
            )
        except scraper.InstagramRateLimitError as e:
            await self._handle_instagram_rate_limit(username, e)
            return

        if platform == data.Platform.INSTAGRAM:
            self.current_instagram_cooldown = float(
                config.INSTAGRAM_CHECK_INTERVAL_SECONDS
            )

        if not posts:
            print(f"No posts found for @{username}, skipping.")
            await self._sleep_with_jitter()
            return

        display_name = posts[0].get("display_name") or username
        self.db.update_display_name(username, display_name, platform=platform)

        post_ids = [p["id"] for p in posts]

        # Newly tracked user: initialize seen cache without notifying
        if not self.db.has_seen_posts_entry(username, platform=platform):
            print(
                f"Initializing seen posts cache for @{username} "
                f"({display_name}) with {len(post_ids)} existing posts."
            )
            self.db.init_user_seen_posts(username, post_ids, platform=platform)
            await self._sleep_with_jitter()
            return

        # Find new posts (oldest first)
        new_posts = [
            p
            for p in reversed(posts)
            if not self.db.is_post_seen(username, p["id"], platform=platform)
        ]

        for post in new_posts:
            # If media is requested by any sub and this is Instagram,
            # enrich media from the post page.
            subs = self.db.get_subscriptions_for_user(
                username, platform=platform
            )
            if (
                platform == data.Platform.INSTAGRAM
                and any(s.get("include_media", False) for s in subs)
                and len(post.get("media_urls", [])) <= 1
            ):
                try:
                    detailed_post = await scraper.scrape_post_by_id(
                        self.bot.browser,
                        post["code"],
                        platform=data.Platform.INSTAGRAM,
                    )
                    if detailed_post and detailed_post.get("media_urls"):
                        post["media_urls"] = detailed_post["media_urls"]
                except scraper.InstagramRateLimitError as e:
                    await self._handle_instagram_rate_limit(username, e)
                    return

            await self._send_alerts(
                username, post, display_name, platform=platform
            )
            self.db.mark_post_seen(username, post["id"], platform=platform)

        await self._sleep_with_jitter()

    async def _send_alerts(
        self,
        username: str,
        post: data.PostDict,
        display_name: str,
        platform: str | data.Platform = data.Platform.THREADS,
    ) -> None:
        """Sends notifications to all channels subscribed to a user's new post.

        Args:
            username: The profile username.
            post: The scraped post dictionary.
            display_name: The display name of the poster.
            platform: The social platform ("threads" or "instagram").
        """
        print(f"New post from {display_name} (@{username}): {post['url']}")
        for sub in self.db.get_subscriptions_for_user(
            username, platform=platform
        ):
            channel = self.bot.get_channel(sub["channel_id"])
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(sub["channel_id"])
                except discord.DiscordException:
                    continue

            payload = utils.format_notification(sub, post, display_name)
            view = utils.get_media_gallery_view(sub, post, payload)
            try:
                if view is not None:
                    await channel.send(view=view)
                else:
                    await channel.send(payload)
                print(
                    f"Sent notification to channel {sub['channel_id']} "
                    f"for post {post['url']}"
                )
            except (discord.DiscordException, OSError) as e:
                print(f"Failed to send to channel {sub['channel_id']}: {e}")

    async def report_error(self, message: str) -> None:
        """Sends traceback error reports to the admin channel.

        Args:
            message: The formatted error report text.
        """
        if not config.ADMIN_CHANNEL_ID:
            return
        try:
            channel = self.bot.get_channel(config.ADMIN_CHANNEL_ID)
            if not channel:
                channel = await self.bot.fetch_channel(config.ADMIN_CHANNEL_ID)
            await channel.send(message)
        except (discord.DiscordException, OSError) as e:
            print(f"Failed to report error to admin channel: {e}")


async def setup(bot: commands.Bot) -> None:
    """Standard setup entrypoint for registering cogs in discord.py.

    Args:
        bot: The commands.Bot instance.
    """
    await bot.add_cog(Monitor(bot))
