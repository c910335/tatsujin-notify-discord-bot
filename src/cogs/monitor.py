"""Background monitoring task for active Threads subscriptions."""

import asyncio
import traceback

import discord
from discord.ext import commands, tasks

import config
import data
import scraper
import utils


class ThreadsMonitor(commands.Cog):
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
        self.monitor_loop.start()

    async def cog_unload(self) -> None:
        """Stops the heartbeat loop task when the cog is unloaded."""
        self.monitor_loop.cancel()

    @tasks.loop(seconds=config.HEARTBEAT_DELAY_SECONDS)
    async def monitor_loop(self) -> None:
        """Background monitoring task to poll public Profiles for updates."""
        print("Heartbeat check started.")
        usernames = self.db.get_all_sub_usernames()

        for username in usernames:
            try:
                await self._check_profile(username)
            except Exception:  # pylint: disable=broad-except
                error_trace = traceback.format_exc()
                print(f"Error checking updates for @{username}:\n{error_trace}")
                await self.report_error(
                    f"Error scraping @{username}:\n"
                    f"```\n{error_trace[:1800]}\n```"
                )

        print("Heartbeat check done.")

    @monitor_loop.before_loop
    async def before_monitor(self) -> None:
        """Awaits ready state before launching the check loop."""
        await self.bot.wait_until_ready()

    async def _check_profile(self, username: str) -> None:
        """Processes a single profile checks for new posts.

        Args:
            username: The Threads username profile to check.
        """
        print(f"Checking updates for Threads profile: @{username}")
        posts: list[data.PostDict] = await scraper.scrape_user_posts(
            self.bot.browser, username
        )

        if not posts:
            print(f"No posts found for @{username}, skipping.")
            await asyncio.sleep(config.CHECK_DELAY_SECONDS)
            return

        display_name = posts[0].get("display_name") or username
        self.db.update_display_name(username, display_name)

        post_ids = [p["id"] for p in posts]

        # Newly tracked user: initialize seen cache without notifying
        if username not in self.db.seen_posts:
            print(
                f"Initializing seen posts cache for @{username} "
                f"({display_name}) with {len(post_ids)} existing posts."
            )
            self.db.init_user_seen_posts(username, post_ids)
            await asyncio.sleep(config.CHECK_DELAY_SECONDS)
            return

        # Find new posts (oldest first)
        new_posts = [
            p
            for p in reversed(posts)
            if not self.db.is_post_seen(username, p["id"])
        ]

        for post in new_posts:
            await self._send_alerts(username, post, display_name)
            self.db.mark_post_seen(username, post["id"])

        await asyncio.sleep(config.CHECK_DELAY_SECONDS)

    async def _send_alerts(
        self, username: str, post: data.PostDict, display_name: str
    ) -> None:
        """Sends notifications to all channels subscribed to a user's new post.

        Args:
            username: The Threads username.
            post: The scraped post dictionary.
            display_name: The display name of the poster.
        """
        print(f"New post from {display_name} (@{username}): {post['url']}")
        for sub in self.db.get_subscriptions_for_user(username):
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
    await bot.add_cog(ThreadsMonitor(bot))
