"""Slash commands cog for managing Threads subscriptions."""

import traceback

import discord
from discord import app_commands
from discord.ext import commands

import config
import data
import scraper
import utils


class ThreadsCommands(commands.Cog):
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
            display = self.db.get_display_name(u)
            label = f"{display} (@{u})"
            if (
                current.lower() in u.lower()
                or current.lower() in display.lower()
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
        description="Subscribe to a Threads profile for the current channel.",
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        username="The Threads username to subscribe to (e.g. c910335)",
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
    ) -> None:
        """Subscribes the current channel to a Threads user's new posts.

        Args:
            interaction: The Discord interaction object.
            username: The Threads username to subscribe to.
            message: Custom message template for notifications.
            mention: Optional user or role to ping on new post.
            overwrite: Whether to overwrite existing subscription.
            include_media: Whether to attach media galleries.
        """
        if "`" in message:
            await interaction.response.send_message(
                "Error: Message template cannot contain backticks (`).",
                ephemeral=True,
            )
            return

        await utils.log_interaction(
            interaction,
            username=username,
            message=message,
            mention=mention,
            overwrite=overwrite,
            include_media=include_media,
        )
        channel_id = interaction.channel_id
        server_id = interaction.guild_id
        mention_str = mention.mention if mention else ""

        success = self.db.add_subscription(
            username=username,
            channel_id=channel_id,
            server_id=server_id,
            message=message,
            mention=mention_str,
            overwrite=overwrite,
            include_media=include_media,
        )

        if success:
            display_name = self.db.get_display_name(username) or username
            mention_desc = (
                f" and will ping {mention_str}" if mention_str else ""
            )
            await interaction.response.send_message(
                (
                    "I will send notifications to "
                    f"<#{channel_id}> with the message"
                    f" (`{message}`){mention_desc} when **{display_name}** "
                    f"(@{username}) posts."
                ),
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                (
                    f"Already subscribed to @{username} in this channel. "
                    f"Pass `overwrite: True` to update the configuration."
                ),
                ephemeral=True,
            )

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
        description=(
            "Unsubscribe from a Threads profile for the current channel."
        ),
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(username="The Threads username to unsubscribe from")
    async def unsubscribe(
        self, interaction: discord.Interaction, username: str
    ) -> None:
        """Unsubscribes the current channel from a Threads user's posts.

        Args:
            interaction: The Discord interaction object.
            username: The Threads username to unsubscribe from.
        """
        await utils.log_interaction(interaction, username=username)
        success = self.db.remove_subscription(username, interaction.channel_id)

        if success:
            await interaction.response.send_message(
                f"Unsubscribed from @{username} in this channel.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                f"No active subscription found for @{username} in this "
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
        description=(
            "List all Threads subscriptions active in the current channel."
        ),
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
            display_name = self.db.get_display_name(sub["username"])
            mention_desc = (
                f" — pings {sub['mention']}" if sub["mention"] else ""
            )
            media_desc = (
                " (no media)" if not sub.get("include_media", False) else ""
            )
            label = (
                f"{idx + 1}. **{display_name}** (@{sub['username']})"
                f"{mention_desc}{media_desc}:"
            )
            lines.append(f"{label}\n```\n{sub['message']}\n```")

        await interaction.response.send_message(
            "\n".join(lines), ephemeral=True
        )

    @app_commands.command(
        name="test",
        description=(
            "Trigger a test notification for a subscribed Threads profile."
        ),
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        username="The Threads username to test",
        silent="If true, the test notification will be visible only to you",
    )
    async def test_notify(
        self, interaction: discord.Interaction, username: str, silent: bool
    ) -> None:
        """Scrapes and outputs a test message using active templates.

        Args:
            interaction: The Discord interaction object.
            username: The Threads username to test.
            silent: Whether to send the test notification ephemerally.
        """
        await utils.log_interaction(
            interaction, username=username, silent=silent
        )
        await interaction.response.defer(ephemeral=silent)
        username = username.strip().lower()

        subs: list[data.SubscriptionDict] = self.db.get_subscriptions_for_user(
            username
        )
        channel_subs: list[data.SubscriptionDict] = [
            s for s in subs if s["channel_id"] == interaction.channel_id
        ]

        if not channel_subs:
            await interaction.followup.send(
                f"No subscription for @{username} in this channel.",
                ephemeral=silent,
            )
            return

        try:
            posts: list[data.PostDict] = await scraper.scrape_user_posts(
                self.bot.browser, username
            )
            if not posts:
                await interaction.followup.send(
                    (
                        f"No posts found for @{username} or profile was not"
                        f" accessible."
                    ),
                    ephemeral=silent,
                )
                return

            latest_post: data.PostDict = posts[0]
            display_name = latest_post.get(
                "display_name"
            ) or self.db.get_display_name(username)
            self.db.update_display_name(username, display_name)

            sub: data.SubscriptionDict = channel_subs[0]
            payload = utils.format_notification(sub, latest_post, display_name)
            view = utils.get_media_gallery_view(sub, latest_post, payload)

            print(
                f"Trigger a test notification for {display_name} (@{username}) "
                f"to {interaction.channel_id}:{interaction.guild_id}"
            )
            if view is not None:
                await interaction.followup.send(view=view, ephemeral=silent)
            else:
                await interaction.followup.send(payload, ephemeral=silent)

        except Exception:  # pylint: disable=broad-except
            error_trace = traceback.format_exc()
            print(f"Test command failed for @{username}:\n{error_trace}")
            await interaction.followup.send(
                (
                    f"**Test Failed for @{username}!**\n"
                    f"Error details:\n```\n{error_trace[:1800]}\n```"
                ),
                ephemeral=silent,
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
            "Send a one-time test notification for a specific Threads post."
        ),
    )
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    @app_commands.default_permissions()
    @app_commands.describe(
        post_id="The specific Threads post ID/code (e.g. DH_eOgcSUww)",
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
    )
    # pylint: disable=too-many-arguments,too-many-locals
    # pylint: disable=too-many-positional-arguments
    async def test_post(
        self,
        interaction: discord.Interaction,
        post_id: str,
        message: str,
        mention: discord.Role | discord.Member | None = None,
        include_media: bool = False,
        silent: bool = False,
    ) -> None:
        """Sends a test notification for a specific post.

        Args:
            interaction: The Discord interaction object.
            post_id: The specific Threads post ID or code.
            message: Custom message template format.
            mention: Optional user or role to ping.
            include_media: Whether to attach media galleries.
            silent: Whether to send the notification ephemerally.
        """
        if "`" in message:
            await interaction.response.send_message(
                "Error: Message template cannot contain backticks (`).",
                ephemeral=True,
            )
            return

        await utils.log_interaction(
            interaction,
            post_id=post_id,
            message=message,
            mention=mention,
            include_media=include_media,
            silent=silent,
        )
        await interaction.response.defer(ephemeral=silent)
        post_id = post_id.strip()

        try:
            post: data.PostDict | None = await scraper.scrape_post_by_id(
                self.bot.browser, post_id
            )
            if not post:
                await interaction.followup.send(
                    f"No post found with ID/code: {post_id}",
                    ephemeral=silent,
                )
                return

            username = post["username"]
            display_name = post.get("display_name") or self.db.get_display_name(
                username
            )
            if display_name:
                self.db.update_display_name(username, display_name)

            mention_str = mention.mention if mention else ""
            # Prepare dummy sub configuration dictionary for formatting
            sub: data.SubscriptionDict = {
                "username": username,
                "channel_id": interaction.channel_id,
                "server_id": interaction.guild_id,
                "message": message,
                "mention": mention_str,
                "include_media": include_media,
            }

            payload = utils.format_notification(sub, post, display_name)
            view = utils.get_media_gallery_view(sub, post, payload)

            print(
                f"Trigger a test post notification for {display_name} "
                f"(@{username}) to {interaction.channel_id}"
            )
            if view is not None:
                await interaction.followup.send(view=view, ephemeral=silent)
            else:
                await interaction.followup.send(payload, ephemeral=silent)

        except Exception:  # pylint: disable=broad-except
            error_trace = traceback.format_exc()
            print(f"Post command failed for {post_id}:\n{error_trace}")
            await interaction.followup.send(
                (
                    f"**Test Failed for post {post_id}!**\n"
                    f"Error details:\n```\n{error_trace[:1800]}\n```"
                ),
                ephemeral=silent,
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
    await bot.add_cog(ThreadsCommands(bot))
