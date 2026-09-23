"""Unit tests for formatting and logging utility functions."""

# pylint: disable=protected-access

import unittest
from unittest import mock

import discord

import config
import data
import utils


class UtilsTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for utils.py helper functions."""

    def test_format_notification_with_all_placeholders(self) -> None:
        """Verifies replacement of all supported variables in a template."""
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "{mention} **{name}** posted: {text} - Link: {url}",
            "mention": "<@&789>",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "Hello World!",
            "timestamp": 1600000000,
            "url": "https://www.threads.com/@testuser/post/C123",
            "media_urls": [],
        }

        result = utils.format_notification(sub, post, "Test User")
        expected = (
            "<@&789> **Test User** posted: Hello World! - "
            "Link: https://www.threads.com/@testuser/post/C123"
        )
        self.assertEqual(result, expected)

    def test_format_notification_prepends_url_if_not_in_message(self) -> None:
        """Verifies that URL is prepended if {url} is missing."""
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "{name} 有新貼文！",
            "mention": "",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "Hello!",
            "timestamp": 1600000000,
            "url": "https://www.threads.com/@testuser/post/C123",
            "media_urls": [],
        }

        result = utils.format_notification(sub, post, "Test User")
        expected = (
            "https://www.threads.com/@testuser/post/C123\nTest User 有新貼文！"
        )
        self.assertEqual(result, expected)

    def test_format_notification_prepends_mention_if_not_in_message(
        self,
    ) -> None:
        """Verifies that mention is prepended if {mention} is missing."""
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "{name} 發文囉！ {url}",
            "mention": "<@&789>",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "Hello!",
            "timestamp": 1600000000,
            "url": "https://www.threads.com/@testuser/post/C123",
            "media_urls": [],
        }

        result = utils.format_notification(sub, post, "Test User")
        expected = (
            "<@&789> Test User 發文囉！ "
            "https://www.threads.com/@testuser/post/C123"
        )
        self.assertEqual(result, expected)

    def test_get_preview_text_logic(self) -> None:
        """Verifies get_preview_text helper logic for characters and lines."""
        # 1. Empty text
        self.assertEqual(utils.get_preview_text(""), "")

        # 2. Text under 100 chars, under 3 lines
        text1 = "line1\nline2"
        self.assertEqual(utils.get_preview_text(text1), "line1\nline2")

        # 3. Text under 100 chars, over 3 lines
        text2 = "line1\nline2\nline3\nline4"
        self.assertEqual(
            utils.get_preview_text(text2), "line1\nline2\nline3\n..."
        )

        # 4. Text over 100 chars, under 3 lines (no newline at truncation)
        text3 = "a" * 110
        self.assertEqual(utils.get_preview_text(text3), "a" * 100 + "...")

        # 5. Text over 100 chars, over 3 lines (no newline at truncation)
        text4 = "a" * 40 + "\n" + "b" * 40 + "\n" + "c" * 40 + "\nline4"
        expected = ("a" * 40 + "\n" + "b" * 40 + "\n" + "c" * 40)[:100] + "..."
        self.assertEqual(utils.get_preview_text(text4), expected)

        # 6. Text over 100 chars, newline at truncation point
        text5 = "a" * 100 + "\nextra"
        self.assertEqual(utils.get_preview_text(text5), "a" * 100 + "\n...")

    def test_format_notification_with_preview_text(self) -> None:
        """Verifies replacement of {preview_text} in message template."""
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "Preview:\n{preview_text}\n{url}",
            "mention": "",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "line1\nline2\nline3\nline4",
            "timestamp": 1600000000,
            "url": "https://www.threads.com/@testuser/post/C123",
            "media_urls": [],
        }
        result = utils.format_notification(sub, post, "Test User")
        expected = (
            "Preview:\nline1\nline2\nline3\n...\n"
            "https://www.threads.com/@testuser/post/C123"
        )
        self.assertEqual(result, expected)

    def test_quote_text_logic(self) -> None:
        """Verifies _quote_text helper wraps lines with '> '."""
        # 1. Empty text
        self.assertEqual(utils._quote_text(""), "")

        # 2. Whitespace-only text
        self.assertEqual(utils._quote_text("   \n  "), "")

        # 3. Single line
        self.assertEqual(utils._quote_text("hello"), "\n> hello\n")

        # 4. Multiple lines
        result = utils._quote_text("line1\nline2\nline3")
        self.assertEqual(result, "\n> line1\n> line2\n> line3\n")

    def test_format_notification_with_quoted_text(self) -> None:
        """Verifies {quoted_text} and {quoted_preview_text} replacements."""
        base_post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "line1\nline2",
            "timestamp": 1600000000,
            "url": "https://url",
            "media_urls": [],
        }

        # 1. quoted_text with non-empty text
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "**{name}**:{quoted_text}{url}",
            "mention": "",
        }
        result = utils.format_notification(sub, base_post, "T")
        self.assertEqual(result, "**T**:\n> line1\n> line2\nhttps://url")

        # 2. quoted_text with empty text
        empty_post = dict(base_post, text="")
        result = utils.format_notification(sub, empty_post, "T")
        self.assertEqual(result, "**T**:https://url")

        # 3. quoted_preview_text with non-empty text
        sub["message"] = "**{name}**:{quoted_preview_text}{url}"
        long_post = dict(
            base_post,
            text="line1\nline2\nline3\nline4",
        )
        result = utils.format_notification(sub, long_post, "T")
        self.assertEqual(
            result,
            "**T**:\n> line1\n> line2\n> line3\n> ...\nhttps://url",
        )

        # 4. quoted_preview_text with empty text
        result = utils.format_notification(sub, empty_post, "T")
        self.assertEqual(result, "**T**:https://url")

    def test_format_notification_with_include_media(self) -> None:
        """Verifies inclusion and exclusion of media URLs."""
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "{name} 發文囉！",
            "mention": "",
            "include_media": True,
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "Hello!",
            "timestamp": 1600000000,
            "url": "https://www.threads.com/@testuser/post/C123",
            "media_urls": ["https://img1.jpg", "https://img2.jpg"],
        }
        # format_notification only returns text
        result = utils.format_notification(sub, post, "Test User")
        expected = (
            "https://www.threads.com/@testuser/post/C123\nTest User 發文囉！"
        )
        self.assertEqual(result, expected)

        # get_media_gallery_view returns LayoutView with MediaGallery
        view = utils.get_media_gallery_view(sub, post, "payload text")
        self.assertIsNotNone(view)
        # Check that it contains a TextDisplay and MediaGallery
        self.assertEqual(len(view.children), 2)
        text_display = view.children[0]
        self.assertEqual(text_display.content, "payload text")
        gallery = view.children[1]
        self.assertEqual(len(gallery.items), 2)
        # Note: Depending on the API, media attribute holds the item.
        # Since it is a v2 component, let's verify it has elements.

        # 2. include_media = False with media URLs (should return None for view)
        sub["include_media"] = False
        view_disabled = utils.get_media_gallery_view(sub, post, "payload text")
        self.assertIsNone(view_disabled)

        # 2b. include_media = True with empty media URLs (returns None)
        sub["include_media"] = True
        post["media_urls"] = []
        view_no_media = utils.get_media_gallery_view(sub, post, "payload text")
        self.assertIsNone(view_no_media)

        # 3. Test with 12 media items
        sub["include_media"] = True
        post["media_urls"] = [f"https://img{i}.jpg" for i in range(12)]
        result_many = utils.format_notification(sub, post, "Test User")
        self.assertIn("2 additional media items were omitted", result_many)

        view_many = utils.get_media_gallery_view(sub, post, result_many)
        self.assertIsNotNone(view_many)
        self.assertEqual(len(view_many.children), 2)
        gallery_many = view_many.children[1]
        self.assertEqual(len(gallery_many.items), 10)

    def test_format_notification_truncates_over_2000_chars(self) -> None:
        """Verifies notification payload is capped at 2000 characters."""
        sub: data.SubscriptionDict = {
            "username": "testuser",
            "channel_id": 123,
            "server_id": 456,
            "message": "Long caption: {text}",
            "mention": "",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "testuser",
            "display_name": "Test User",
            "text": "A" * 2500,
            "timestamp": 1600000000,
            "url": "https://www.threads.com/@testuser/post/C123",
            "media_urls": [],
        }
        result = utils.format_notification(sub, post, "Test User")
        self.assertEqual(len(result), 2000)
        self.assertTrue(result.endswith("..."))

    async def test_log_interaction_sends_to_admin(self) -> None:
        """Verifies logging command sends notification to admin channel."""
        mock_interaction = mock.MagicMock()
        mock_interaction.user.name = "testuser"
        mock_interaction.user.mention = "<@123>"
        mock_interaction.channel_id = 456
        mock_interaction.guild_id = 789
        mock_interaction.command.name = "subscribe"

        mock_client = mock.MagicMock()
        mock_channel = mock.MagicMock()
        mock_channel.send = mock.AsyncMock()
        mock_client.get_channel.return_value = None
        mock_client.fetch_channel = mock.AsyncMock(return_value=mock_channel)
        mock_interaction.client = mock_client

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 999):
            await utils.log_interaction(mock_interaction, username="targetuser")

        mock_client.get_channel.assert_called_once_with(999)
        mock_client.fetch_channel.assert_called_once_with(999)
        mock_channel.send.assert_called_once()
        self.assertIn("targetuser", mock_channel.send.call_args[0][0])

    async def test_log_interaction_handles_exception_gracefully(self) -> None:
        """Verifies that error in sending to admin is handled gracefully."""
        mock_interaction = mock.MagicMock()
        mock_interaction.user.name = "testuser"
        mock_interaction.user.mention = "<@123>"
        mock_interaction.channel_id = 456
        mock_interaction.guild_id = 789
        mock_interaction.command.name = "subscribe"

        mock_client = mock.MagicMock()
        mock_client.get_channel.side_effect = discord.DiscordException(
            "Discord Error"
        )
        mock_interaction.client = mock_client

        with mock.patch.object(config, "ADMIN_CHANNEL_ID", 999):
            # This should not raise an exception
            await utils.log_interaction(mock_interaction, username="targetuser")

    def test_parse_target_input(self) -> None:
        """Verifies parsing of URLs and identifiers for Threads and
        Instagram.
        """
        # Empty string
        self.assertEqual(utils.parse_target_input(""), ("threads", ""))

        # Instagram profile URL
        self.assertEqual(
            utils.parse_target_input("https://www.instagram.com/nasa/"),
            ("instagram", "nasa"),
        )
        self.assertEqual(
            utils.parse_target_input("https://instagram.com/pumashen"),
            ("instagram", "pumashen"),
        )

        # Instagram post and reel URLs
        self.assertEqual(
            utils.parse_target_input(
                "https://www.instagram.com/p/DdEo7DPG8x2/"
            ),
            ("instagram", "DdEo7DPG8x2"),
        )
        self.assertEqual(
            utils.parse_target_input(
                "https://www.instagram.com/reel/DcMXl1IPNtB/"
            ),
            ("instagram", "DcMXl1IPNtB"),
        )

        # Threads profile URLs
        self.assertEqual(
            utils.parse_target_input("https://www.threads.net/@c910335"),
            ("threads", "c910335"),
        )
        self.assertEqual(
            utils.parse_target_input("https://www.threads.com/@c910335/"),
            ("threads", "c910335"),
        )

        # Threads post URLs
        self.assertEqual(
            utils.parse_target_input(
                "https://www.threads.com/@c910335/post/DH_eOgcSUww"
            ),
            ("threads", "DH_eOgcSUww"),
        )
        self.assertEqual(
            utils.parse_target_input(
                "https://www.threads.com/post/DH_eOgcSUww"
            ),
            ("threads", "DH_eOgcSUww"),
        )

        # Scheme-less URLs
        self.assertEqual(
            utils.parse_target_input("instagram.com/nasa"),
            ("instagram", "nasa"),
        )
        self.assertEqual(
            utils.parse_target_input("threads.net/@c910335"),
            ("threads", "c910335"),
        )

        # Bare usernames and handles
        self.assertEqual(
            utils.parse_target_input("@nasa", default_platform="instagram"),
            ("instagram", "nasa"),
        )
        self.assertEqual(
            utils.parse_target_input("c910335"),
            ("threads", "c910335"),
        )

    def test_format_notification_instagram_fallback_url(self) -> None:
        """Verifies Instagram URL fallback when {url} is omitted."""
        sub: data.SubscriptionDict = {
            "username": "nasa",
            "channel_id": 123,
            "server_id": 456,
            "message": "{name} 有新動態！",
            "mention": "",
            "include_media": False,
            "platform": "instagram",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "DdEo7DPG8x2",
            "username": "nasa",
            "display_name": "NASA",
            "text": "Space news!",
            "timestamp": 1600000000,
            "url": None,
            "media_urls": [],
        }

        result = utils.format_notification(sub, post, "NASA")
        expected = "https://www.instagram.com/p/DdEo7DPG8x2/\nNASA 有新動態！"
        self.assertEqual(result, expected)

    def test_format_notification_threads_fallback_url(self) -> None:
        """Verifies Threads URL fallback when post url is missing."""
        sub: data.SubscriptionDict = {
            "username": "c910335",
            "channel_id": 123,
            "server_id": 456,
            "message": "{name}: {url}",
            "mention": "",
            "include_media": False,
            "platform": "threads",
        }
        post: data.PostDict = {
            "id": "post123",
            "code": "C123",
            "username": "c910335",
            "display_name": "達人",
            "text": "Hello",
            "timestamp": 1600000000,
            "url": None,
            "media_urls": [],
        }

        result = utils.format_notification(sub, post, "達人")
        expected = "達人: https://www.threads.com/@c910335/post/C123"
        self.assertEqual(result, expected)

    def test_format_duration(self) -> None:
        """Verifies duration formatting for various seconds values."""
        self.assertEqual(utils.format_duration(0), "0s")
        self.assertEqual(utils.format_duration(45), "45s")
        self.assertEqual(utils.format_duration(60), "1m")
        self.assertEqual(utils.format_duration(90), "1m 30s")
        self.assertEqual(utils.format_duration(1800), "30m")
        self.assertEqual(utils.format_duration(3600), "1h")
        self.assertEqual(utils.format_duration(3665), "1h 1m 5s")
        self.assertEqual(utils.format_duration(7200), "2h")
        self.assertEqual(utils.format_duration(43200), "12h")
        self.assertEqual(utils.format_duration(-5), "0s")


if __name__ == "__main__":
    unittest.main()
