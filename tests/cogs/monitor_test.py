"""Unit tests for ThreadsMonitor background polling loop cog."""

# pylint: disable=protected-access,duplicate-code,consider-using-with

import os
import tempfile
import unittest
from unittest import mock

import discord
from discord.ext import commands

import config
import data
from cogs import monitor


class ThreadsMonitorTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for ThreadsMonitor cog."""

    def setUp(self) -> None:
        """Sets up custom testing file paths and mock bot context."""
        self.test_dir = self.enterContext(tempfile.TemporaryDirectory())
        data.DataStore.DATA_FILE = os.path.join(
            self.test_dir, "test_monitor_data.json"
        )
        data.DataStore.SEEN_FILE = os.path.join(
            self.test_dir, "test_monitor_seen.json"
        )
        data.DataStore.DISPLAY_NAMES_FILE = os.path.join(
            self.test_dir, "test_monitor_display_names.json"
        )

        # Initialize clean data store
        self.db = data.get_data_store()
        self.db.subscriptions = []
        self.db.seen_posts = {}
        self.db.display_names = {}

        # Mock Bot
        self.mock_bot = mock.MagicMock(spec=commands.Bot)
        self.mock_bot.browser = mock.MagicMock()
        # Prevent loop from starting upon instantiation
        with mock.patch("discord.ext.tasks.Loop.start"):
            self.monitor_cog = monitor.ThreadsMonitor(self.mock_bot)

    async def test_monitor_check_profile_new_post(self) -> None:
        """Verifies background monitor task detects and alerts on new posts."""
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)
        # Initialize seen posts with an older post
        self.db.init_user_seen_posts("c910335", ["old_post_id"])

        mock_channel = mock.AsyncMock()
        self.mock_bot.get_channel.return_value = mock_channel

        mock_posts = [
            {
                "id": "new_post_id",
                "code": "NewCode",
                "username": "c910335",
                "display_name": "達人",
                "text": "New post!",
                "timestamp": 1700000000,
                "url": "https://www.threads.com/@c910335/post/NewCode",
                "media_urls": [],
            },
            {
                "id": "old_post_id",
                "code": "OldCode",
                "username": "c910335",
                "display_name": "達人",
                "text": "Old post!",
                "timestamp": 1600000000,
                "url": "https://www.threads.com/@c910335/post/OldCode",
                "media_urls": [],
            },
        ]

        with mock.patch("scraper.scrape_user_posts", return_value=mock_posts):
            await self.monitor_cog._check_profile("c910335")

        # Verify only the new post is marked seen and notified
        self.assertTrue(self.db.is_post_seen("c910335", "new_post_id"))
        mock_channel.send.assert_called_once()
        self.assertIn(
            "https://www.threads.com/@c910335/post/NewCode",
            mock_channel.send.call_args[0][0],
        )

    async def test_monitor_report_error_sends_to_admin(self) -> None:
        """Verifies report_error sends reports correctly to admin channel."""
        mock_channel = mock.AsyncMock()
        self.mock_bot.get_channel.return_value = None
        self.mock_bot.fetch_channel = mock.AsyncMock(return_value=mock_channel)

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 999):
            await self.monitor_cog.report_error("Traceback error details")

        self.mock_bot.get_channel.assert_called_once_with(999)
        self.mock_bot.fetch_channel.assert_called_once_with(999)
        mock_channel.send.assert_called_once_with("Traceback error details")

    async def test_monitor_loop_exception_reporting(self) -> None:
        """Verifies monitor loop logs and reports errors to admin channel."""
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)

        # Mock check_profile to raise exception
        with mock.patch.object(
            self.monitor_cog, "_check_profile", side_effect=Exception("Crash")
        ):
            with mock.patch.object(
                self.monitor_cog, "report_error"
            ) as mock_report:
                with mock.patch.object(
                    self.monitor_cog, "before_monitor"
                ) as mock_before:
                    mock_before.return_value = None
                    # Run the loop function directly
                    await self.monitor_cog.monitor_loop.coro(self.monitor_cog)

        mock_report.assert_called_once()
        self.assertIn("Error scraping @c910335", mock_report.call_args[0][0])

    async def test_monitor_before_loop_ready(self) -> None:
        """Verifies monitor cog awaits bot readiness before running loop."""
        self.mock_bot.wait_until_ready = mock.AsyncMock()
        await self.monitor_cog.before_monitor()
        self.mock_bot.wait_until_ready.assert_called_once()

    async def test_monitor_check_profile_empty_and_new_user(self) -> None:
        """Verifies check_profile with no posts and new subscriptions."""
        # 1. No posts found
        with mock.patch("scraper.scrape_user_posts", return_value=[]):
            await self.monitor_cog._check_profile("c910335")
        self.assertNotIn("c910335", self.db.seen_posts)

        # 2. Newly subscribed user (initializes seen cache without alerting)
        self.db.add_subscription("c910335", 111, 222, "msg", "", False)
        mock_posts = [
            {
                "id": "post1",
                "username": "c910335",
                "display_name": "達人",
                "text": "H",
                "timestamp": 1,
                "url": "https://url",
                "media_urls": [],
            }
        ]

        with mock.patch("scraper.scrape_user_posts", return_value=mock_posts):
            await self.monitor_cog._check_profile("c910335")

        self.assertTrue(self.db.is_post_seen("c910335", "post1"))

    async def test_monitor_send_alerts_cached_channel_and_failures(
        self,
    ) -> None:
        """Verifies _send_alerts with channel retrieval and send failures."""
        post: data.PostDict = {
            "id": "1",
            "code": "C",
            "username": "user",
            "display_name": "User",
            "text": "T",
            "timestamp": 1,
            "url": "https://url",
            "media_urls": ["https://example.com/media.jpg"],
        }
        self.db.add_subscription(
            "user", 111, 222, "msg", "", False, include_media=True
        )

        # 1. Cached channel works
        mock_channel = mock.AsyncMock()
        self.mock_bot.get_channel.return_value = mock_channel
        await self.monitor_cog._send_alerts("user", post, "User")
        mock_channel.send.assert_called_once()
        kwargs = mock_channel.send.call_args[1]
        self.assertIn("view", kwargs)
        self.assertIsNotNone(kwargs["view"])

        # 2. Fetch channel fails
        self.mock_bot.get_channel.return_value = None
        self.mock_bot.fetch_channel = mock.AsyncMock(
            side_effect=discord.DiscordException("Fetch Fail")
        )
        mock_channel.send.reset_mock()
        await self.monitor_cog._send_alerts("user", post, "User")
        mock_channel.send.assert_not_called()

        # 3. Send fails
        self.mock_bot.get_channel.return_value = mock_channel
        mock_channel.send.side_effect = discord.DiscordException("Send Fail")
        # Should catch exception and log to stdout without crashing
        await self.monitor_cog._send_alerts("user", post, "User")

    async def test_monitor_report_error_cached_admin(self) -> None:
        """Verifies report_error uses cached admin channel if available."""
        mock_channel = mock.AsyncMock()
        self.mock_bot.get_channel.return_value = mock_channel
        self.mock_bot.fetch_channel = mock.AsyncMock()

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 999):
            await self.monitor_cog.report_error("Some error")

        self.mock_bot.get_channel.assert_called_once_with(999)
        self.mock_bot.fetch_channel.assert_not_called()
        mock_channel.send.assert_called_once_with("Some error")

    async def test_monitor_report_error_exception_grace(self) -> None:
        """Verifies report_error handles exceptions gracefully."""
        self.mock_bot.get_channel.side_effect = discord.DiscordException(
            "Crash"
        )
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 999):
            await self.monitor_cog.report_error("Some error")

    async def test_monitor_report_error_disabled(self) -> None:
        """Verifies report_error returns early when ADMIN_CHANNEL_ID is 0."""
        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 0):
            await self.monitor_cog.report_error("Some error")
        self.mock_bot.get_channel.assert_not_called()

    async def test_setup_monitor(self) -> None:
        """Verifies setup registers ThreadsMonitor cog."""
        mock_bot = mock.MagicMock(spec=commands.Bot)
        mock_bot.add_cog = mock.AsyncMock()
        # Prevent loop from starting upon instantiation
        with mock.patch("discord.ext.tasks.Loop.start"):
            await monitor.setup(mock_bot)
        mock_bot.add_cog.assert_called_once()

    async def test_cog_unload(self) -> None:
        """Verifies cog_unload cancels the monitor loop."""
        self.monitor_cog.monitor_loop = mock.MagicMock()
        await self.monitor_cog.cog_unload()
        self.monitor_cog.monitor_loop.cancel.assert_called_once()


if __name__ == "__main__":
    unittest.main()
