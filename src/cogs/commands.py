"""Slash commands cog for managing subscriptions."""

import traceback
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

import config
import data
import scraper
import utils


def _format_subscription_notice(
    sub: data.SubscriptionDict,
    display_name: str,
) -> str:
    """Formats confirmation notice for newly added subscription.

    Args:
        sub: The subscription configuration dictionary.
        display_name: Formatted display name.

    Returns:
        The message string to reply with.
    """
    platform_desc = (
        f" on {sub['platform'].capitalize()}"
        if sub["platform"] == data.Platform.INSTAGRAM
        else ""
    )
    mention_desc = f" and will ping {sub['mention']}" if sub["mention"] else ""
    return (
        f"I will send notifications to <#{sub['channel_id']}> with the message"
        f" (`{sub['message']}`){mention_desc} when **{display_name}** "
        f"(@{sub['username']}{platform_desc}) posts."
    )


def _format_duplicate_notice(
    username: str,
    platform: str,
) -> str:
    """Formats notice when subscription already exists in channel.

    Args:
        username: Cleaned social media username.
        platform: Social platform string.

    Returns:
        The message string to reply with.
    """
    platform_desc = (
        f" on {platform.capitalize()}"
        if platform == data.Platform.INSTAGRAM
        else ""
    )
    return (
        f"Already subscribed to @{username}{platform_desc} in this "
        "channel. Pass `overwrite: True` to update the configuration."
    )


def _format_sub_item(
    db: data.DataStore, idx: int, sub: data.SubscriptionDict
) -> str:
    """Formats an individual subscription item for /list.

    Args:
        db: The DataStore instance.
        idx: 0-based index of the subscription.
        sub: The subscription dictionary.

    Returns:
        Formatted string describing the subscription.
    """
    sub_platform = sub.get("platform", data.Platform.THREADS)
    display_name = db.get_display_name(sub["username"], platform=sub_platform)
    mention_desc = f" — pings {sub['mention']}" if sub["mention"] else ""
    media_desc = " (no media)" if not sub.get("include_media", False) else ""
    platform_badge = f"[{sub_platform.capitalize()}] "
    label = (
        f"{idx + 1}. **{platform_badge}{display_name}** "
        f"(@{sub['username']}){mention_desc}{media_desc}:"
    )
    return f"{label}\n```\n{sub['message']}\n```"


def _chunk_message_lines(lines: list[str], max_len: int = 1900) -> list[str]:
    """Chunks formatted lines to stay within Discord 2000-char message limits.

    Args:
        lines: List of message lines.
        max_len: Maximum character length per chunk.

    Returns:
        List of chunked message strings.
    """
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current_len + line_len > max_len and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = [line]
            current_len = len(line)
        else:
            current_chunk.append(line)
            current_len += line_len
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    return chunks


def _find_channel_sub(
    db: data.DataStore,
    username: str,
    channel_id: int | None,
    platform: str | None,
) -> data.SubscriptionDict | None:
    """Finds a matching subscription for a user in a specific channel.

    Args:
        db: The DataStore instance.
        username: The cleaned username.
        channel_id: The Discord channel ID.
        platform: Optional platform filter.

    Returns:
        SubscriptionDict if found, None otherwise.
    """
    subs = db.get_subscriptions_for_user(username, platform=platform)
    channel_subs = [s for s in subs if s["channel_id"] == channel_id]
    return channel_subs[0] if channel_subs else None


async def _fetch_test_user_post(
    browser: Any, username: str, target_sub: data.SubscriptionDict
) -> data.PostDict | None:
    """Fetches the latest post for a test notification.

    Args:
        browser: Active Playwright browser instance.
        username: Cleaned username.
        target_sub: Subscription dictionary for configuration.

    Returns:
        PostDict if found, None otherwise.
    """
    actual_platform = target_sub.get("platform", data.Platform.THREADS)
    posts = await scraper.scrape_user_posts(
        browser, username, platform=actual_platform
    )
    if not posts:
        return None

    latest_post = posts[0]
    if (
        actual_platform == data.Platform.INSTAGRAM
        and target_sub.get("include_media", False)
        and len(latest_post.get("media_urls", [])) <= 1
    ):
        detailed = await scraper.scrape_post_by_id(
            browser, latest_post["code"], platform=data.Platform.INSTAGRAM
        )
        if detailed and detailed.get("media_urls"):
            latest_post["media_urls"] = detailed["media_urls"]
    return latest_post


async def _send_post_notification(
    interaction: discord.Interaction,
    sub: data.SubscriptionDict,
    post: data.PostDict,
    display_name: str,
    silent: bool,
) -> None:
    """Dispatches a formatted notification message or gallery view.

    Args:
        interaction: Discord interaction to reply to.
        sub: Subscription configuration.
        post: Scraped post data.
        display_name: Resolved user display name.
        silent: Whether response should be ephemeral.
    """
    payload = utils.format_notification(sub, post, display_name)
    view = utils.get_media_gallery_view(sub, post, payload)

    print(
        f"Trigger a test notification for {display_name} "
        f"(@{sub['username']}) to "
        f"{interaction.channel_id}:{interaction.guild_id}"
    )
    if view is not None:
        await interaction.followup.send(view=view, ephemeral=silent)
    else:
        await interaction.followup.send(payload, ephemeral=silent)


async def _send_error_feedback(
    interaction: discord.Interaction,
    log_msg: str,
    user_msg: str,
    silent: bool,
) -> None:
    """Prints and responds with formatted exception traceback.

    Args:
        interaction: Discord interaction to reply to.
        log_msg: Message to print to server logs.
        user_msg: Header message to show to the user.
        silent: Whether response should be ephemeral.
    """
    error_trace = traceback.format_exc()
    print(f"{log_msg}:\n{error_trace}")
    await interaction.followup.send(
        (
            f"**{user_msg}!**\n"
            f"Error details:\n```\n{error_trace[:1800]}\n```"
        ),
        ephemeral=silent,
    )


class Commands(commands.Cog):
    """Cog grouping all subscription configuration slash commands."""

    def __init__(
        self,
        bot: commands.Bot,
        data_store: data.DataStore | None = None,
    ) -> None:
        """Initializes the commands cog.

        Args:
            bot: The commands.Bot instance.
            data_store: Optional custom DataStore instance.
        """
        self.bot = bot
        self.db = data_store or data.get_data_store()

    async def autocomplete_username(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Helper to autocomplete username choice from active subscriptions.

        Args:
            interaction: The Discord interaction object.
            current: The current text typed by the user.

        Returns:
            A list of up to 25 autocompleted username choices.
        """
        subs: list[data.SubscriptionDict] = self.db.list_subscriptions(
            interaction.channel_id
        )
        choices = []
        for sub in subs:
            u = sub["username"]
            p = sub.get("platform", data.Platform.THREADS)
            display = self.db.get_display_name(u, platform=p)
            platform_tag = (
                f"[{p.capitalize()}] " if p == data.Platform.INSTAGRAM else ""
            )
            label = f"{platform_tag}{display} (@{u})"
            if len(label) > 100:
                label = label[:97] + "..."
            if (
                current.lower() in u.lower()
                or current.lower() in display.lower()
                or current.lower() in p.lower()
            ):
                choices.append(app_commands.Choice(name=label, value=u))
        return choices[:25]

    async def autocomplete_message(
        self, _interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Helper to autocomplete message template options.

        Args:
            _interaction: The Discord interaction object (unused).
            current: The current text typed by the user.

        Returns:
            A list of matching message template choices.
        """
        return [
            app_commands.Choice(name=t, value=t)
            for t in config.NOTIFICATION_MESSAGE_TEMPLATES
            if current.lower() in t.lower()
        ][:25]

    @app_commands.command(
        name="subscribe",
        description="Subscribe to a Threads or Instagram profile.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        username=(
            "The profile username or URL "
            "(e.g. threads.net/@c910335 or instagram.com/snackssion.ig)"
        ),
        message=(
            "Message template (supports {name}, {text}, "
            "{preview_text}, {quoted_text}, "
            "{quoted_preview_text}, {url}, {mention})"
        ),
        mention="The role or user to notify when a new post is found",
        overwrite=(
            "Overwrite the existing subscription if one already exists "
            "(default: False)"
        ),
        include_media=(
            "Whether to include post images/videos in notifications (default:"
            " False)"
        ),
        platform=(
            "The platform to subscribe to: Threads or Instagram "
            "(default: Threads)"
        ),
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Threads", value=data.Platform.THREADS),
            app_commands.Choice(
                name="Instagram", value=data.Platform.INSTAGRAM
            ),
        ]
    )
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    async def subscribe(
        self,
        interaction: discord.Interaction,
        username: str,
        message: str,
        mention: discord.Role | discord.Member | None = None,
        overwrite: bool = False,
        include_media: bool = False,
        platform: str = data.Platform.THREADS,
    ) -> None:
        """Subscribes the current channel to a user's new posts.

        Args:
            interaction: The Discord interaction object.
            username: The profile username or URL to subscribe to.
            message: Custom message template for notifications.
            mention: Optional user or role to ping on new post.
            overwrite: Whether to overwrite existing subscription.
            include_media: Whether to attach media galleries.
            platform: Social media platform ("threads" or "instagram").
        """
        if "`" in message:
            await interaction.response.send_message(
                "Error: Message template cannot contain backticks (`).",
                ephemeral=True,
            )
            return

        detected_platform, clean_username = utils.parse_target_input(
            username, default_platform=platform
        )

        await utils.log_interaction(
            interaction,
            username=clean_username,
            message=message,
            mention=mention,
            overwrite=overwrite,
            include_media=include_media,
            platform=detected_platform,
        )
        mention_str = mention.mention if mention else ""
        success = self.db.add_subscription(
            username=clean_username,
            channel_id=interaction.channel_id,
            server_id=interaction.guild_id,
            message=message,
            mention=mention_str,
            overwrite=overwrite,
            include_media=include_media,
            platform=detected_platform,
        )

        if success:
            display_name = (
                self.db.get_display_name(
                    clean_username, platform=detected_platform
                )
                or clean_username
            )
            feedback = _format_subscription_notice(
                {
                    "username": clean_username,
                    "channel_id": interaction.channel_id,
                    "server_id": interaction.guild_id,
                    "message": message,
                    "mention": mention_str,
                    "include_media": include_media,
                    "platform": detected_platform,
                },
                display_name,
            )
        else:
            feedback = _format_duplicate_notice(
                clean_username, detected_platform
            )
        await interaction.response.send_message(feedback, ephemeral=True)

    @subscribe.autocomplete("username")
    async def subscribe_username_auto(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocompletes username parameter for subscribe command.

        Args:
            interaction: The Discord interaction object.
            current: The current text typed by the user.

        Returns:
            A list of autocompleted username choices.
        """
        return await self.autocomplete_username(interaction, current)

    @subscribe.autocomplete("message")
    async def subscribe_message_auto(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocompletes message parameter for subscribe command.

        Args:
            interaction: The Discord interaction object.
            current: The current text typed by the user.

        Returns:
            A list of matching message template choices.
        """
        return await self.autocomplete_message(interaction, current)

    @app_commands.command(
        name="unsubscribe",
        description="Unsubscribe from a profile for the current channel.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        username=(
            "The username or profile URL "
            "(e.g. threads.net/@c910335 or instagram.com/snackssion.ig)"
        ),
        platform="Platform filter: Threads or Instagram (optional)",
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Threads", value=data.Platform.THREADS),
            app_commands.Choice(
                name="Instagram", value=data.Platform.INSTAGRAM
            ),
        ]
    )
    async def unsubscribe(
        self,
        interaction: discord.Interaction,
        username: str,
        platform: str | None = None,
    ) -> None:
        """Unsubscribes the current channel from a user's posts.

        Args:
            interaction: The Discord interaction object.
            username: The username to unsubscribe from.
            platform: Optional platform filter.
        """
        detected_platform = platform
        if (
            username.startswith(("http://", "https://"))
            or "instagram.com" in username
            or "threads." in username
        ):
            detected_platform, clean_username = utils.parse_target_input(
                username, default_platform=platform or data.Platform.THREADS
            )
        else:
            clean_username = username.lstrip("@").strip().lower()

        await utils.log_interaction(
            interaction, username=clean_username, platform=detected_platform
        )
        success = self.db.remove_subscription(
            clean_username,
            interaction.channel_id,
            platform=detected_platform,
        )

        if success:
            await interaction.response.send_message(
                f"Unsubscribed from @{clean_username} in this channel.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"No active subscription found for @{clean_username} in this "
                "channel.",
                ephemeral=True,
            )

    @unsubscribe.autocomplete("username")
    async def unsubscribe_username_auto(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocompletes username parameter for unsubscribe command.

        Args:
            interaction: The Discord interaction object.
            current: The current text typed by the user.

        Returns:
            A list of autocompleted username choices.
        """
        return await self.autocomplete_username(interaction, current)

    @app_commands.command(
        name="list",
        description="List all subscriptions active in the current channel.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    async def list_subs(self, interaction: discord.Interaction) -> None:
        """Lists active subscription configurations in the channel.

        Args:
            interaction: The Discord interaction object.
        """
        await utils.log_interaction(interaction)
        subs: list[data.SubscriptionDict] = self.db.list_subscriptions(
            interaction.channel_id
        )

        if not subs:
            await interaction.response.send_message(
                "No active subscriptions in this channel.", ephemeral=True
            )
            return

        lines = ["**Active Subscriptions for this Channel:**"]
        for idx, sub in enumerate(subs):
            lines.append(_format_sub_item(self.db, idx, sub))

        chunks = _chunk_message_lines(lines)
        await interaction.response.send_message(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

    @app_commands.command(
        name="test",
        description="Trigger a test notification for a subscribed profile.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        username=(
            "The username or profile URL "
            "(e.g. threads.net/@c910335 or instagram.com/snackssion.ig)"
        ),
        silent="If true, the test notification will be visible only to you",
        platform="Platform to test: Threads or Instagram (optional)",
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Threads", value=data.Platform.THREADS),
            app_commands.Choice(
                name="Instagram", value=data.Platform.INSTAGRAM
            ),
        ]
    )
    async def test_notify(
        self,
        interaction: discord.Interaction,
        username: str,
        silent: bool,
        platform: str | None = None,
    ) -> None:
        """Scrapes and outputs a test message using active templates.

        Args:
            interaction: The Discord interaction object.
            username: The username to test.
            silent: Whether to send the test notification ephemerally.
            platform: Optional platform filter.
        """
        if (
            username.startswith(("http://", "https://"))
            or "instagram.com" in username
            or "threads." in username
        ):
            detected_platform, clean_username = utils.parse_target_input(
                username, default_platform=platform or data.Platform.THREADS
            )
        else:
            detected_platform = platform
            clean_username = username.lstrip("@").strip().lower()

        await utils.log_interaction(
            interaction,
            username=clean_username,
            silent=silent,
            platform=detected_platform,
        )
        await interaction.response.defer(ephemeral=silent)

        target_sub = _find_channel_sub(
            self.db, clean_username, interaction.channel_id, detected_platform
        )
        if not target_sub:
            await interaction.followup.send(
                f"No subscription for @{clean_username} in this channel.",
                ephemeral=silent,
            )
            return

        try:
            post = await _fetch_test_user_post(
                self.bot.browser, clean_username, target_sub
            )
            if not post:
                await interaction.followup.send(
                    (
                        f"No posts found for @{clean_username} or profile was"
                        " not accessible."
                    ),
                    ephemeral=silent,
                )
                return

            actual_platform = target_sub.get("platform", data.Platform.THREADS)
            display_name = post.get("display_name") or self.db.get_display_name(
                clean_username, platform=actual_platform
            )
            self.db.update_display_name(
                clean_username, display_name, platform=actual_platform
            )

            await _send_post_notification(
                interaction, target_sub, post, display_name, silent
            )
        except scraper.InstagramRateLimitError:
            await interaction.followup.send(
                f"Failed to fetch test post for @{clean_username}: Instagram "
                "is currently rate-limiting access. Please try again later.",
                ephemeral=silent,
            )
        except Exception:  # pylint: disable=broad-except
            await _send_error_feedback(
                interaction,
                f"Test command failed for @{clean_username}",
                f"Test Failed for @{clean_username}",
                silent,
            )

    @test_notify.autocomplete("username")
    async def test_username_auto(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocompletes username parameter for test command.

        Args:
            interaction: The Discord interaction object.
            current: The current text typed by the user.

        Returns:
            A list of autocompleted username choices.
        """
        return await self.autocomplete_username(interaction, current)

    @app_commands.command(
        name="post",
        description=(
            "Send a one-time test notification for a Threads or Instagram post."
        ),
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        post_id=(
            "The post ID, code, or URL "
            "(e.g. DH_eOgcSUww or instagram.com/p/C_ACjgVvIX4)"
        ),
        message=(
            "Message template (supports {name}, {text}, "
            "{preview_text}, {quoted_text}, "
            "{quoted_preview_text}, {url}, {mention})"
        ),
        mention="The role or user to notify",
        include_media=(
            "Whether to include post images/videos in notifications (default:"
            " False)"
        ),
        silent="Whether to send the notification silently (default: False)",
        platform="Platform: Threads or Instagram (default: Threads)",
    )
    @app_commands.choices(
        platform=[
            app_commands.Choice(name="Threads", value=data.Platform.THREADS),
            app_commands.Choice(
                name="Instagram", value=data.Platform.INSTAGRAM
            ),
        ]
    )
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    async def test_post(
        self,
        interaction: discord.Interaction,
        post_id: str,
        message: str,
        mention: discord.Role | discord.Member | None = None,
        include_media: bool = False,
        silent: bool = False,
        platform: str = data.Platform.THREADS,
    ) -> None:
        """Sends a test notification for a specific post.

        Args:
            interaction: The Discord interaction object.
            post_id: The specific post ID, code, or post URL.
            message: Custom message template format.
            mention: Optional user or role to ping.
            include_media: Whether to attach media galleries.
            silent: Whether to send the notification ephemerally.
            platform: Social platform ("threads" or "instagram").
        """
        if "`" in message:
            await interaction.response.send_message(
                "Error: Message template cannot contain backticks (`).",
                ephemeral=True,
            )
            return

        detected_platform, clean_post_id = utils.parse_target_input(
            post_id, default_platform=platform
        )

        await utils.log_interaction(
            interaction,
            post_id=clean_post_id,
            message=message,
            mention=mention,
            include_media=include_media,
            silent=silent,
            platform=detected_platform,
        )
        await interaction.response.defer(ephemeral=silent)

        try:
            post = await scraper.scrape_post_by_id(
                self.bot.browser, clean_post_id, platform=detected_platform
            )
            if not post:
                await interaction.followup.send(
                    f"No post found with ID/code: {clean_post_id}",
                    ephemeral=silent,
                )
                return

            username = post["username"]
            display_name = post.get("display_name") or self.db.get_display_name(
                username, platform=detected_platform
            )
            if display_name:
                self.db.update_display_name(
                    username, display_name, platform=detected_platform
                )

            sub: data.SubscriptionDict = {
                "username": username,
                "channel_id": interaction.channel_id,
                "server_id": interaction.guild_id,
                "message": message,
                "mention": mention.mention if mention else "",
                "include_media": include_media,
                "platform": detected_platform,
            }
            resolved_name = display_name or username
            await _send_post_notification(
                interaction, sub, post, resolved_name, silent
            )
        except scraper.InstagramRateLimitError:
            await interaction.followup.send(
                f"Failed to fetch post {clean_post_id}: Instagram "
                "is currently rate-limiting access. Please try again later.",
                ephemeral=silent,
            )
        except Exception:  # pylint: disable=broad-except
            await _send_error_feedback(
                interaction,
                f"Post command failed for {clean_post_id}",
                f"Test Failed for post {clean_post_id}",
                silent,
            )

    @test_post.autocomplete("message")
    async def test_post_message_auto(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocompletes message parameter for post command.

        Args:
            interaction: The Discord interaction object.
            current: The current text typed by the user.

        Returns:
            A list of matching message template choices.
        """
        return await self.autocomplete_message(interaction, current)


async def setup(bot: commands.Bot) -> None:
    """Standard setup entrypoint for registering cogs in discord.py.

    Args:
        bot: The commands.Bot instance.
    """
    await bot.add_cog(Commands(bot))
