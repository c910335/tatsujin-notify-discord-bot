"""Unit tests for Commands slash commands cog."""

# pylint: disable=protected-access,duplicate-code,consider-using-with
# pylint: disable=too-many-public-methods

import os
import tempfile
import unittest
from unittest import mock

import discord
from discord.ext import commands

import config
import data
import scraper
from cogs import commands as cog_commands


class CommandsTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for Commands cog."""

    def setUp(self) -> None:
        """Sets up custom testing file paths and mock bot context."""
        self.test_dir = self.enterContext(tempfile.TemporaryDirectory())
        data.DataStore.DATA_FILE = os.path.join(
            self.test_dir, "test_commands_data.json"
        )
        data.DataStore.SEEN_FILE = os.path.join(
            self.test_dir, "test_commands_seen.json"
        )
        data.DataStore.DISPLAY_NAMES_FILE = os.path.join(
            self.test_dir, "test_commands_display_names.json"
        )

        # Initialize clean data store
        self.db = data.get_data_store()
        self.db.subscriptions = []
        self.db.seen_posts = {}
        self.db.display_names = {}

        # Mock Bot
        self.mock_bot = mock.MagicMock(spec=commands.Bot)
        self.mock_bot.browser = mock.MagicMock()
        self.commands_cog = cog_commands.Commands(self.mock_bot)

    async def test_subscribe_command_success(self) -> None:
        """Verifies /subscribe command registers a subscription."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "subscribe"

        # Mock interaction response
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        # Set ADMIN_CHANNEL_ID to 0 to bypass interaction logging in tests
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.subscribe.callback(
                self.commands_cog,
                interaction=mock_interaction,
                username="c910335",
                message="hello {name} {url}",
                mention=None,
                overwrite=False,
                include_media=False,
            )

        # Verify subscription was added
        subs = self.db.list_subscriptions(111)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["username"], "c910335")
        self.assertFalse(subs[0]["include_media"])
        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "I will send notifications",
            mock_interaction.response.send_message.call_args[0][0],
        )

    async def test_subscribe_command_rejects_backticks(self) -> None:
        """Verifies /subscribe command rejects templates with backticks."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        await self.commands_cog.subscribe.callback(
            self.commands_cog,
            interaction=mock_interaction,
            username="c910335",
            message="hello `backtick`",
            mention=None,
            overwrite=False,
            include_media=False,
        )

        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "cannot contain backticks",
            mock_interaction.response.send_message.call_args[0][0],
        )
        # Check no subscription was added
        self.assertEqual(len(self.db.list_subscriptions(111)), 0)

    async def test_subscribe_command_conflict_without_overwrite(self) -> None:
        """Verifies /subscribe command rejects duplicates without overwrite."""
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "subscribe"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.subscribe.callback(
                self.commands_cog,
                interaction=mock_interaction,
                username="c910335",
                message="new msg",
                mention=None,
                overwrite=False,
            )

        # Verify subscription did not change
        subs = self.db.list_subscriptions(111)
        self.assertEqual(subs[0]["message"], "msg")
        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "Already subscribed",
            mock_interaction.response.send_message.call_args[0][0],
        )

    async def test_unsubscribe_command_success(self) -> None:
        """Verifies /unsubscribe command removes active subscriptions."""
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "unsubscribe"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.unsubscribe.callback(
                self.commands_cog, mock_interaction, "c910335"
            )

        subs = self.db.list_subscriptions(111)
        self.assertEqual(len(subs), 0)
        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "Unsubscribed from",
            mock_interaction.response.send_message.call_args[0][0],
        )

    async def test_unsubscribe_command_not_found(self) -> None:
        """Verifies /unsubscribe command handles missing subscription."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "unsubscribe"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.unsubscribe.callback(
                self.commands_cog, mock_interaction, "c910335"
            )

        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "No active subscription",
            mock_interaction.response.send_message.call_args[0][0],
        )

    async def test_list_subs_command_empty(self) -> None:
        """Verifies /list command output when no subscriptions are present."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "list"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.list_subs.callback(
                self.commands_cog, mock_interaction
            )

        mock_interaction.response.send_message.assert_called_once_with(
            "No active subscriptions in this channel.", ephemeral=True
        )

    async def test_list_subs_command_populated(self) -> None:
        """Verifies /list command formats and displays subscriptions."""
        self.db.add_subscription(
            "c910335",
            111,
            222,
            "msg\n>>> {text}",
            "<@&1>",
            False,
            include_media=False,
        )

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "list"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.list_subs.callback(
                self.commands_cog, mock_interaction
            )

        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "Active Subscriptions for this Channel:",
            mock_interaction.response.send_message.call_args[0][0],
        )
        self.assertIn(
            "c910335",
            mock_interaction.response.send_message.call_args[0][0],
        )
        self.assertIn(
            "```\nmsg\n>>> {text}\n```",
            mock_interaction.response.send_message.call_args[0][0],
        )
        self.assertIn(
            "(no media)",
            mock_interaction.response.send_message.call_args[0][0],
        )
        self.assertIn(
            "[Threads]",
            mock_interaction.response.send_message.call_args[0][0],
        )

    async def test_list_subs_command_chunks_overflow(self) -> None:
        """Verifies /list command chunks messages when exceeding limit."""
        for i in range(15):
            self.db.add_subscription(
                f"user_{i}",
                111,
                222,
                "A" * 150,
                "",
                False,
            )

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "list"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.list_subs.callback(
                self.commands_cog, mock_interaction
            )

        mock_interaction.response.send_message.assert_called_once()
        mock_interaction.followup.send.assert_called()

    async def test_test_notify_command_success(self) -> None:
        """Verifies /test command triggers manual fetch successfully."""
        self.db.add_subscription("c910335", 111, 222, "msg {url}", "", False)

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "test"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        mock_posts = [
            {
                "id": "post123",
                "code": "C123",
                "username": "c910335",
                "display_name": "達人",
                "text": "Hello",
                "timestamp": 1600000000,
                "url": "https://www.threads.com/@c910335/post/C123",
                "media_urls": [],
            }
        ]

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_user_posts", return_value=mock_posts
            ):
                await self.commands_cog.test_notify.callback(
                    self.commands_cog, mock_interaction, "c910335", False
                )

        mock_interaction.response.defer.assert_called_once_with(ephemeral=False)
        mock_interaction.followup.send.assert_called_once()
        self.assertIn(
            "https://www.threads.com/@c910335/post/C123",
            mock_interaction.followup.send.call_args[0][0],
        )

    async def test_test_notify_command_success_with_media(self) -> None:
        """Verifies /test command sends MediaGallery view successfully."""
        self.db.add_subscription(
            "c910335", 111, 222, "msg {url}", "", False, include_media=True
        )

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "test"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        mock_posts = [
            {
                "id": "post123",
                "code": "C123",
                "username": "c910335",
                "display_name": "達人",
                "text": "Hello",
                "timestamp": 1600000000,
                "url": "https://www.threads.com/@c910335/post/C123",
                "media_urls": ["https://img1.jpg"],
            }
        ]

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_user_posts", return_value=mock_posts
            ):
                await self.commands_cog.test_notify.callback(
                    self.commands_cog, mock_interaction, "c910335", False
                )

        mock_interaction.response.defer.assert_called_once_with(ephemeral=False)
        mock_interaction.followup.send.assert_called_once()
        kwargs = mock_interaction.followup.send.call_args[1]
        self.assertIn("view", kwargs)
        self.assertIsNotNone(kwargs["view"])

    async def test_autocomplete_username_and_message(self) -> None:
        """Verifies autocompleters return correct choices."""
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)
        self.db.update_display_name("c910335", "達人")

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111

        # Test autocomplete username
        choices = await self.commands_cog.autocomplete_username(
            mock_interaction, "c91"
        )
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].name, "達人 (@c910335)")
        self.assertEqual(choices[0].value, "c910335")

        # Test autocomplete message
        msg_choices = await self.commands_cog.autocomplete_message(
            mock_interaction, "發布"
        )
        self.assertEqual(len(msg_choices), 1)
        self.assertIn("發布", msg_choices[0].value)

    async def test_test_notify_no_posts_and_error(self) -> None:
        """Verifies /test command behavior when scraping fails."""
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "test"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        # 1. No posts found
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch("scraper.scrape_user_posts", return_value=[]):
                await self.commands_cog.test_notify.callback(
                    self.commands_cog, mock_interaction, "c910335", False
                )
        self.assertIn(
            "No posts found", mock_interaction.followup.send.call_args[0][0]
        )

        # 2. Scraper raises exception
        mock_interaction.followup.send.reset_mock()
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_user_posts",
                side_effect=Exception("Scrape error"),
            ):
                await self.commands_cog.test_notify.callback(
                    self.commands_cog, mock_interaction, "c910335", False
                )
        self.assertIn(
            "Test Failed", mock_interaction.followup.send.call_args[0][0]
        )

        # 3. Instagram rate limit error
        mock_interaction.followup.send.reset_mock()
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_user_posts",
                side_effect=scraper.InstagramRateLimitError("Rate limited"),
            ):
                await self.commands_cog.test_notify.callback(
                    self.commands_cog, mock_interaction, "c910335", False
                )
        self.assertIn(
            "Instagram is currently rate-limiting access",
            mock_interaction.followup.send.call_args[0][0],
        )

    async def test_autocomplete_username_with_active_subscription(self) -> None:
        """Verifies autocomplete_username returns matching choices."""
        self.db.add_subscription("c910335", 111, 222, "msg1", "", False)
        self.db.update_display_name("c910335", "達人")

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111

        choices = await self.commands_cog.autocomplete_username(
            mock_interaction, "c91"
        )
        self.assertEqual(len(choices), 1)

        # Long display name truncation to stay <= 100 chars
        self.db.add_subscription("longuser", 111, 222, "msg", "", False)
        self.db.update_display_name("longuser", "X" * 150)
        choices_long = await self.commands_cog.autocomplete_username(
            mock_interaction, "long"
        )
        self.assertEqual(len(choices_long), 1)
        self.assertEqual(len(choices_long[0].name), 100)
        self.assertTrue(choices_long[0].name.endswith("..."))

    async def test_test_notify_not_subscribed(self) -> None:
        """Verifies /test command behavior when not subscribed."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "test"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        # Target user is not subscribed
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.test_notify.callback(
                self.commands_cog, mock_interaction, "c910335", False
            )

        self.assertIn(
            "No subscription for @c910335",
            mock_interaction.followup.send.call_args[0][0],
        )

    async def test_setup_commands(self) -> None:
        """Verifies setup registers Commands cog."""
        mock_bot = mock.MagicMock(spec=commands.Bot)
        mock_bot.add_cog = mock.AsyncMock()
        await cog_commands.setup(mock_bot)
        mock_bot.add_cog.assert_called_once()

    async def test_post_command_success(self) -> None:
        """Verifies /post command successfully handles test notification."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.command.name = "post"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        post_data = {
            "id": "123_456",
            "code": "DH_eOgcSUww",
            "username": "c910335",
            "display_name": "達人",
            "text": "Hello world",
            "timestamp": 1234567,
            "url": "https://url",
            "media_urls": [],
        }

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_post_by_id", return_value=post_data
            ):
                await self.commands_cog.test_post.callback(
                    self.commands_cog,
                    interaction=mock_interaction,
                    post_id="DH_eOgcSUww",
                    message="hello {name} {url}",
                    mention=None,
                    include_media=False,
                )

        mock_interaction.response.defer.assert_called_once()
        mock_interaction.followup.send.assert_called_once()
        sent_msg = mock_interaction.followup.send.call_args[0][0]
        self.assertIn("hello 達人 https://url", sent_msg)
        self.assertEqual(self.db.get_display_name("c910335"), "達人")

    async def test_post_command_success_with_media(self) -> None:
        """Verifies /post command successfully includes media views."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.command.name = "post"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        post_data = {
            "id": "123_456",
            "code": "DH_eOgcSUww",
            "username": "c910335",
            "display_name": "達人",
            "text": "Hello world",
            "timestamp": 1234567,
            "url": "https://url",
            "media_urls": ["https://img.jpg"],
        }

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_post_by_id", return_value=post_data
            ):
                await self.commands_cog.test_post.callback(
                    self.commands_cog,
                    interaction=mock_interaction,
                    post_id="DH_eOgcSUww",
                    message="hello {name} {url}",
                    mention=None,
                    include_media=True,
                )

        mock_interaction.response.defer.assert_called_once_with(ephemeral=False)
        mock_interaction.followup.send.assert_called_once()
        kwargs = mock_interaction.followup.send.call_args[1]
        self.assertIn("view", kwargs)
        self.assertIsNotNone(kwargs["view"])

    async def test_post_command_not_found(self) -> None:
        """Verifies /post command handles case when post is not found."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.command.name = "post"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch("scraper.scrape_post_by_id", return_value=None):
                await self.commands_cog.test_post.callback(
                    self.commands_cog,
                    interaction=mock_interaction,
                    post_id="DH_eOgcSUww",
                    message="hello {name}",
                    mention=None,
                    include_media=False,
                )

        mock_interaction.followup.send.assert_called_once()
        self.assertIn(
            "No post found",
            mock_interaction.followup.send.call_args[0][0],
        )

    async def test_post_command_error(self) -> None:
        """Verifies /post command handles scraping exceptions gracefully."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.command.name = "post"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_post_by_id",
                side_effect=Exception("Scrape error"),
            ):
                await self.commands_cog.test_post.callback(
                    self.commands_cog,
                    interaction=mock_interaction,
                    post_id="DH_eOgcSUww",
                    message="hello {name}",
                    mention=None,
                    include_media=False,
                )

        mock_interaction.followup.send.assert_called_once()
        self.assertIn(
            "Test Failed for post",
            mock_interaction.followup.send.call_args[0][0],
        )

    async def test_post_command_instagram_rate_limit(self) -> None:
        """Verifies /post handles InstagramRateLimitError with clean message."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.command.name = "post"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_post_by_id",
                side_effect=scraper.InstagramRateLimitError("Rate limited"),
            ):
                await self.commands_cog.test_post.callback(
                    self.commands_cog,
                    interaction=mock_interaction,
                    post_id="https://www.instagram.com/p/DdEo7DPG8x2/",
                    message="hello {name}",
                    mention=None,
                    include_media=False,
                )

        mock_interaction.followup.send.assert_called_once()
        self.assertIn(
            "Instagram is currently rate-limiting access",
            mock_interaction.followup.send.call_args[0][0],
        )

    async def test_post_command_rejects_backticks(self) -> None:
        """Verifies /post command rejects message template with backticks."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        await self.commands_cog.test_post.callback(
            self.commands_cog,
            interaction=mock_interaction,
            post_id="DH_eOgcSUww",
            message="hello `backtick`",
            mention=None,
            include_media=False,
        )

        mock_interaction.response.send_message.assert_called_once()
        self.assertIn(
            "cannot contain backticks",
            mock_interaction.response.send_message.call_args[0][0],
        )

    async def test_autocomplete_wrappers(self) -> None:
        """Verifies autocomplete wrappers call the underlying handler."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111

        with mock.patch.object(
            self.commands_cog,
            "autocomplete_username",
            new_callable=mock.AsyncMock,
        ) as mock_user:
            await self.commands_cog.subscribe_username_auto(
                mock_interaction, "foo"
            )
            mock_user.assert_called_once_with(mock_interaction, "foo")

            mock_user.reset_mock()
            await self.commands_cog.unsubscribe_username_auto(
                mock_interaction, "foo"
            )
            mock_user.assert_called_once_with(mock_interaction, "foo")

            mock_user.reset_mock()
            await self.commands_cog.test_username_auto(mock_interaction, "foo")
            mock_user.assert_called_once_with(mock_interaction, "foo")

        with mock.patch.object(
            self.commands_cog,
            "autocomplete_message",
            new_callable=mock.AsyncMock,
        ) as mock_msg:
            await self.commands_cog.subscribe_message_auto(
                mock_interaction, "foo"
            )
            mock_msg.assert_called_once_with(mock_interaction, "foo")

            mock_msg.reset_mock()
            await self.commands_cog.test_post_message_auto(
                mock_interaction, "foo"
            )
            mock_msg.assert_called_once_with(mock_interaction, "foo")

    async def test_subscribe_command_instagram_url_autodetect(self) -> None:
        """Verifies /subscribe command auto-detects Instagram from URL."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "subscribe"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.subscribe.callback(
                self.commands_cog,
                interaction=mock_interaction,
                username="https://www.instagram.com/nasa/",
                message="NASA IG: {url}",
                mention=None,
                overwrite=False,
                include_media=True,
                platform="threads",  # Defaults to threads, but URL overrides
            )

        subs = self.db.list_subscriptions(111)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["username"], "nasa")
        self.assertEqual(subs[0]["platform"], "instagram")
        self.assertTrue(subs[0]["include_media"])

    async def test_unsubscribe_command_instagram_url(self) -> None:
        """Verifies /unsubscribe command accepts Instagram URLs."""
        self.db.add_subscription(
            "nasa", 111, 222, "msg", "", False, platform="instagram"
        )
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "unsubscribe"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.unsubscribe.callback(
                self.commands_cog,
                mock_interaction,
                "https://www.instagram.com/nasa/",
            )

        subs = self.db.list_subscriptions(111)
        self.assertEqual(len(subs), 0)

    async def test_test_notify_instagram_with_media_enrichment(self) -> None:
        """Verifies /test enriches media carousel for Instagram
        subscriptions.
        """
        self.db.add_subscription(
            "nasa",
            111,
            222,
            "NASA {url}",
            "",
            False,
            include_media=True,
            platform="instagram",
        )

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "test"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        mock_posts = [
            {
                "id": "ig_123",
                "code": "DdEo7DPG8x2",
                "username": "nasa",
                "display_name": "NASA",
                "text": "Space news",
                "timestamp": 1700000000,
                "url": "https://www.instagram.com/p/DdEo7DPG8x2/",
                "media_urls": ["https://example.com/thumb.jpg"],
            }
        ]
        detailed_post = {
            "id": "ig_123",
            "code": "DdEo7DPG8x2",
            "username": "nasa",
            "display_name": "NASA",
            "text": "Space news",
            "timestamp": 1700000000,
            "url": "https://www.instagram.com/p/DdEo7DPG8x2/",
            "media_urls": [
                "https://example.com/1.jpg",
                "https://example.com/2.jpg",
            ],
        }

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_user_posts", return_value=mock_posts
            ) as mock_user_scrape:
                with mock.patch(
                    "scraper.scrape_post_by_id", return_value=detailed_post
                ) as mock_post_scrape:
                    await self.commands_cog.test_notify.callback(
                        self.commands_cog,
                        mock_interaction,
                        "https://www.instagram.com/nasa/",
                        False,
                    )

        mock_user_scrape.assert_called_once_with(
            self.mock_bot.browser, "nasa", platform="instagram"
        )
        mock_post_scrape.assert_called_once_with(
            self.mock_bot.browser, "DdEo7DPG8x2", platform="instagram"
        )
        mock_interaction.followup.send.assert_called_once()
        kwargs = mock_interaction.followup.send.call_args[1]
        self.assertIn("view", kwargs)

    async def test_post_command_instagram_url(self) -> None:
        """Verifies /post command handles Instagram post URLs."""
        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.user.mention = "<@admin>"
        mock_interaction.command.name = "post"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.defer = mock.AsyncMock()
        mock_interaction.followup = mock.MagicMock()
        mock_interaction.followup.send = mock.AsyncMock()

        mock_post: data.PostDict = {
            "id": "post_ig_1",
            "code": "DdEo7DPG8x2",
            "username": "nasa",
            "display_name": "NASA",
            "text": "Hello IG",
            "timestamp": 1700000000,
            "url": "https://www.instagram.com/p/DdEo7DPG8x2/",
            "media_urls": [],
        }

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            with mock.patch(
                "scraper.scrape_post_by_id", return_value=mock_post
            ) as mock_scrape:
                await self.commands_cog.test_post.callback(
                    self.commands_cog,
                    interaction=mock_interaction,
                    post_id="https://www.instagram.com/p/DdEo7DPG8x2/",
                    message="hello {name} {url}",
                    mention=None,
                    include_media=False,
                    platform="threads",
                )

        mock_scrape.assert_called_once_with(
            self.mock_bot.browser, "DdEo7DPG8x2", platform="instagram"
        )
        mock_interaction.followup.send.assert_called_once()

    async def test_list_and_autocomplete_instagram(self) -> None:
        """Verifies /list and autocompleter format Instagram badges."""
        self.db.add_subscription(
            "nasa", 111, 222, "msg", "", False, platform="instagram"
        )
        self.db.update_display_name(
            "nasa", "NASA Official", platform="instagram"
        )

        mock_interaction = mock.MagicMock(spec=discord.Interaction)
        mock_interaction.channel_id = 111
        mock_interaction.guild_id = 222
        mock_interaction.user.name = "adminuser"
        mock_interaction.command.name = "list"
        mock_interaction.response = mock.MagicMock()
        mock_interaction.response.send_message = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.commands_cog.list_subs.callback(
                self.commands_cog, mock_interaction
            )

        content = mock_interaction.response.send_message.call_args[0][0]
        self.assertIn("[Instagram]", content)
        self.assertIn("@nasa", content)

        # Autocomplete
        choices = await self.commands_cog.autocomplete_username(
            mock_interaction, "nas"
        )
        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].name, "[Instagram] NASA Official (@nasa)")
        self.assertEqual(choices[0].value, "nasa")


if __name__ == "__main__":
    unittest.main()
