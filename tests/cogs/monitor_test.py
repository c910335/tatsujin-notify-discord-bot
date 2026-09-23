"""Unit tests for Monitor background polling loop cog."""

# pylint: disable=protected-access,duplicate-code,consider-using-with

import os
import tempfile
import time
import unittest
from unittest import mock

import discord
from discord.ext import commands

import config
import data
import scraper
from cogs import monitor


class MonitorTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for Monitor cog."""

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
            self.monitor_cog = monitor.Monitor(self.mock_bot)

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
        """Verifies setup registers Monitor cog."""
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

    async def test_monitor_check_profile_instagram_media_enrichment(
        self,
    ) -> None:
        """Verifies Instagram posts enrich media carousel when requested."""
        self.db.add_subscription(
            "nasa",
            111,
            222,
            "msg",
            "",
            False,
            include_media=True,
            platform="instagram",
        )
        self.db.init_user_seen_posts(
            "nasa", ["old_ig_post"], platform="instagram"
        )

        mock_channel = mock.AsyncMock()
        self.mock_bot.get_channel.return_value = mock_channel

        timeline_post: data.PostDict = {
            "id": "new_ig_post",
            "code": "DdEo7DPG8x2",
            "username": "nasa",
            "display_name": "NASA",
            "text": "IG update",
            "timestamp": 1700000000,
            "url": "https://www.instagram.com/p/DdEo7DPG8x2/",
            "media_urls": ["https://example.com/thumb.jpg"],
        }
        detailed_post: data.PostDict = {
            "id": "new_ig_post",
            "code": "DdEo7DPG8x2",
            "username": "nasa",
            "display_name": "NASA",
            "text": "IG update",
            "timestamp": 1700000000,
            "url": "https://www.instagram.com/p/DdEo7DPG8x2/",
            "media_urls": [
                "https://example.com/slide1.jpg",
                "https://example.com/slide2.jpg",
            ],
        }

        with mock.patch(
            "scraper.scrape_user_posts", return_value=[timeline_post]
        ) as mock_scrape_user:
            with mock.patch(
                "scraper.scrape_post_by_id", return_value=detailed_post
            ) as mock_scrape_post:
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )

        mock_scrape_user.assert_called_once_with(
            self.mock_bot.browser, "nasa", platform="instagram"
        )
        mock_scrape_post.assert_called_once_with(
            self.mock_bot.browser, "DdEo7DPG8x2", platform="instagram"
        )
        self.assertTrue(
            self.db.is_post_seen("nasa", "new_ig_post", platform="instagram")
        )
        mock_channel.send.assert_called_once()
        self.assertEqual(
            timeline_post["media_urls"],
            [
                "https://example.com/slide1.jpg",
                "https://example.com/slide2.jpg",
            ],
        )

    async def test_monitor_loop_iterates_all_platforms(self) -> None:
        """Verifies monitor_loop iterates over all unique targets."""
        self.db.add_subscription(
            "threads_user", 111, 222, "msg", "", False, platform="threads"
        )
        self.db.add_subscription(
            "ig_user", 111, 222, "msg", "", False, platform="instagram"
        )

        with mock.patch.object(
            self.monitor_cog, "_check_profile"
        ) as mock_check:
            with mock.patch.object(
                self.monitor_cog, "before_monitor", return_value=None
            ):
                await self.monitor_cog.monitor_loop.coro(self.monitor_cog)

        self.assertEqual(mock_check.call_count, 2)
        mock_check.assert_any_call("threads_user", platform="threads")
        mock_check.assert_any_call("ig_user", platform="instagram")

    async def test_monitor_instagram_rate_limit_cooldown(self) -> None:
        """Verifies Instagram rate limit activates cooldown and skips checks."""
        with mock.patch.object(self.monitor_cog, "report_error") as mock_report:
            with mock.patch(
                "scraper.scrape_user_posts",
                side_effect=scraper.InstagramRateLimitError("Rate limit test"),
            ):
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )

            mock_report.assert_called_once()
            self.assertIn("Rate limit", mock_report.call_args[0][0])
            self.assertIn("20m", mock_report.call_args[0][0])
            self.assertGreater(self.monitor_cog.instagram_cooldown_until, 0)
            self.assertEqual(
                self.monitor_cog.current_instagram_cooldown, 2400.0
            )

            # Subsequent Instagram check during cooldown skips scraper entirely
            with mock.patch("scraper.scrape_user_posts") as mock_scrape_after:
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )
                mock_scrape_after.assert_not_called()

            # Second rate limit doubles cooldown to 40m
            self.monitor_cog.instagram_cooldown_until = 0.0
            self.monitor_cog.last_checked_times.clear()
            mock_report.reset_mock()
            with mock.patch(
                "scraper.scrape_user_posts",
                side_effect=scraper.InstagramRateLimitError(
                    "Second rate limit"
                ),
            ):
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )
            mock_report.assert_called_once()
            self.assertIn("40m", mock_report.call_args[0][0])
            self.assertEqual(
                self.monitor_cog.current_instagram_cooldown, 4800.0
            )

            # Cooldown caps at INSTAGRAM_MAX_COOLDOWN_SECONDS
            self.monitor_cog.current_instagram_cooldown = (
                float(config.INSTAGRAM_MAX_COOLDOWN_SECONDS) - 100.0
            )
            self.monitor_cog.instagram_cooldown_until = 0.0
            self.monitor_cog.last_checked_times.clear()
            with mock.patch(
                "scraper.scrape_user_posts",
                side_effect=scraper.InstagramRateLimitError(
                    "Capped rate limit"
                ),
            ):
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )
            self.assertEqual(
                self.monitor_cog.current_instagram_cooldown,
                float(config.INSTAGRAM_MAX_COOLDOWN_SECONDS),
            )

            # Successful Instagram scrape resets cooldown back to base
            self.monitor_cog.instagram_cooldown_until = 0.0
            self.monitor_cog.last_checked_times.clear()
            with mock.patch(
                "scraper.scrape_user_posts", return_value=[]
            ) as mock_success:
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )
                mock_success.assert_called_once()
                self.assertEqual(
                    self.monitor_cog.current_instagram_cooldown,
                    float(config.INSTAGRAM_CHECK_INTERVAL_SECONDS),
                )

            # Threads check is NOT blocked by Instagram cooldown
            self.monitor_cog.instagram_cooldown_until = time.time() + 3600
            with mock.patch(
                "scraper.scrape_user_posts", return_value=[]
            ) as mock_scrape_threads:
                await self.monitor_cog._check_profile(
                    "c910335", platform="threads"
                )
                mock_scrape_threads.assert_called_once()

    async def test_monitor_instagram_rate_limit_during_media_enrichment(
        self,
    ) -> None:
        """Verifies rate limit during media enrichment activates cooldown."""
        self.db.add_subscription(
            "nasa",
            111,
            222,
            "msg",
            "",
            False,
            include_media=True,
            platform="instagram",
        )
        self.db.init_user_seen_posts(
            "nasa", ["old_ig_post"], platform="instagram"
        )

        timeline_post: data.PostDict = {
            "id": "new_ig_post",
            "code": "DdEo7DPG8x2",
            "username": "nasa",
            "display_name": "NASA",
            "text": "IG update",
            "timestamp": 1700000000,
            "url": "https://www.instagram.com/p/DdEo7DPG8x2/",
            "media_urls": ["https://example.com/thumb.jpg"],
        }

        with mock.patch.object(self.monitor_cog, "report_error") as mock_report:
            with mock.patch(
                "scraper.scrape_user_posts", return_value=[timeline_post]
            ):
                with mock.patch(
                    "scraper.scrape_post_by_id",
                    side_effect=scraper.InstagramRateLimitError("Enrich limit"),
                ):
                    await self.monitor_cog._check_profile(
                        "nasa", platform="instagram"
                    )

            mock_report.assert_called_once()
            self.assertIn("Enrich limit", mock_report.call_args[0][0])
            self.assertGreater(self.monitor_cog.instagram_cooldown_until, 0)
            self.assertFalse(
                self.db.is_post_seen(
                    "nasa", "new_ig_post", platform="instagram"
                )
            )

    async def test_sleep_with_jitter(self) -> None:
        """Verifies _sleep_with_jitter calls asyncio.sleep with delay."""
        with mock.patch("asyncio.sleep") as mock_sleep:
            await self.monitor_cog._sleep_with_jitter()
            mock_sleep.assert_called_once()
            delay = mock_sleep.call_args[0][0]
            self.assertGreaterEqual(delay, config.CHECK_DELAY_SECONDS)
            self.assertLessEqual(
                delay, config.CHECK_DELAY_SECONDS + config.CHECK_JITTER_SECONDS
            )

        # Zero jitter case
        with mock.patch.object(config, "CHECK_JITTER_SECONDS", 0.0):
            with mock.patch("asyncio.sleep") as mock_sleep:
                await self.monitor_cog._sleep_with_jitter()
                mock_sleep.assert_called_once_with(config.CHECK_DELAY_SECONDS)

    async def test_monitor_loop_heartbeat_jitter(self) -> None:
        """Verifies monitor_loop applies jitter to change_interval."""
        with mock.patch.object(
            self.monitor_cog.monitor_loop, "change_interval"
        ) as mock_change:
            with mock.patch.object(
                self.monitor_cog, "before_monitor", return_value=None
            ):
                await self.monitor_cog.monitor_loop.coro(self.monitor_cog)
            mock_change.assert_called_once()
            call_sec = mock_change.call_args[1]["seconds"]
            self.assertGreaterEqual(
                call_sec,
                config.HEARTBEAT_DELAY_SECONDS
                - config.HEARTBEAT_JITTER_SECONDS,
            )
            self.assertLessEqual(
                call_sec,
                config.HEARTBEAT_DELAY_SECONDS
                + config.HEARTBEAT_JITTER_SECONDS,
            )

        # Zero jitter case
        with mock.patch.object(config, "HEARTBEAT_JITTER_SECONDS", 0.0):
            with mock.patch.object(
                self.monitor_cog.monitor_loop, "change_interval"
            ) as mock_change:
                with mock.patch.object(
                    self.monitor_cog, "before_monitor", return_value=None
                ):
                    await self.monitor_cog.monitor_loop.coro(self.monitor_cog)
                mock_change.assert_not_called()

    async def test_monitor_instagram_check_interval(self) -> None:
        """Verifies Instagram checks respect check interval seconds."""
        with mock.patch(
            "scraper.scrape_user_posts", return_value=[]
        ) as mock_scrape:
            # 1. First check executes and records last_checked_time
            await self.monitor_cog._check_profile("nasa", platform="instagram")
            self.assertEqual(mock_scrape.call_count, 1)
            self.assertIn(
                ("nasa", "instagram"), self.monitor_cog.last_checked_times
            )

            # 2. Immediate second check skips scraper due to interval
            await self.monitor_cog._check_profile("nasa", platform="instagram")
            self.assertEqual(mock_scrape.call_count, 1)

            # 3. Check after interval elapses executes scraper again
            future_time = (
                time.time() + config.INSTAGRAM_CHECK_INTERVAL_SECONDS + 10
            )
            with mock.patch("time.time", return_value=future_time):
                await self.monitor_cog._check_profile(
                    "nasa", platform="instagram"
                )
                self.assertEqual(mock_scrape.call_count, 2)


if __name__ == "__main__":
    unittest.main()
