"""Unit tests for the DataStore thread-safe JSON persistence storage layer."""

# pylint: disable=protected-access,duplicate-code,consider-using-with
# pylint: disable=too-many-public-methods

import json
import os
import tempfile
import unittest
from unittest import mock

import data


class DataStoreTest(unittest.TestCase):
    """Test cases for the thread-safe JSON persistence storage layer."""

    def setUp(self) -> None:
        """Sets up custom testing file paths and initializes a fresh store."""
        self.test_dir = self.enterContext(tempfile.TemporaryDirectory())
        data.DataStore.DATA_FILE = os.path.join(self.test_dir, "test_data.json")
        data.DataStore.SEEN_FILE = os.path.join(
            self.test_dir, "test_seen_posts.json"
        )
        data.DataStore.DISPLAY_NAMES_FILE = os.path.join(
            self.test_dir, "test_display_names.json"
        )
        self.store = data.DataStore()

    def test_load_empty_or_missing_files(self) -> None:
        """Verifies that missing files are handled gracefully during loading."""
        self.assertEqual(self.store.subscriptions, [])
        self.assertEqual(self.store.seen_posts, {})

    def test_load_corrupt_files_handles_gracefully(self) -> None:
        """Verifies recovery behavior when files contain invalid JSON."""
        # Create invalid files on disk
        with open(data.DataStore.DATA_FILE, "w", encoding="utf-8") as f:
            f.write("invalid json")
        with open(data.DataStore.SEEN_FILE, "w", encoding="utf-8") as f:
            f.write("invalid json")
        with open(
            data.DataStore.DISPLAY_NAMES_FILE, "w", encoding="utf-8"
        ) as f:
            f.write("invalid json")

        # Loading should recover and load empty datasets
        store = data.DataStore()
        self.assertEqual(store.subscriptions, [])
        self.assertEqual(store.seen_posts, {})
        self.assertEqual(store.display_names, {})

    def test_safe_write_handles_exceptions(self) -> None:
        """Verifies safe writing handles write errors gracefully."""
        # Make a write attempt raise OSError on rename
        with mock.patch("os.replace", side_effect=OSError("Disk Full")):
            with self.assertRaises(OSError):
                self.store._safe_write(data.DataStore.DATA_FILE, {"test": 123})

    def test_add_subscription_creates_new(self) -> None:
        """Verifies that adding a new subscription stores it correctly."""
        self.store.add_subscription(
            username="c910335",
            channel_id=111,
            server_id=222,
            message="hello",
            mention="<@&123>",
            overwrite=False,
            include_media=False,
        )
        subs = self.store.list_subscriptions(111)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["username"], "c910335")
        self.assertEqual(subs[0]["message"], "hello")
        self.assertEqual(subs[0]["mention"], "<@&123>")
        self.assertFalse(subs[0]["include_media"])

    def test_add_subscription_rejects_duplicate_without_overwrite(self) -> None:
        """Verifies duplicates are rejected when overwrite is false."""
        self.store.add_subscription("c910335", 111, 222, "msg1", "", False)
        result = self.store.add_subscription(
            "c910335", 111, 222, "msg2", "", False
        )
        self.assertFalse(result)

        # Check message did not get updated
        subs = self.store.list_subscriptions(111)
        self.assertEqual(subs[0]["message"], "msg1")

    def test_add_subscription_updates_with_overwrite(self) -> None:
        """Verifies subscription updates when overwrite is true."""
        self.store.add_subscription(
            "c910335", 111, 222, "msg1", "", False, include_media=False
        )
        result = self.store.add_subscription(
            "c910335", 111, 222, "msg2", "", True, include_media=True
        )
        self.assertTrue(result)

        # Check message and include_media did get updated
        subs = self.store.list_subscriptions(111)
        self.assertEqual(subs[0]["message"], "msg2")
        self.assertTrue(subs[0]["include_media"])

    def test_remove_subscription_success(self) -> None:
        """Verifies removing subscription succeeds if it exists."""
        self.store.add_subscription("c910335", 111, 222, "msg", "", False)
        self.store.init_user_seen_posts("c910335", ["post1"])
        self.store.update_display_name("c910335", "達人")
        removed = self.store.remove_subscription("c910335", 111)
        self.assertTrue(removed)
        self.assertEqual(len(self.store.list_subscriptions(111)), 0)
        self.assertNotIn("threads:c910335", self.store.seen_posts)
        self.assertEqual(self.store.get_display_name("c910335"), "c910335")

    def test_remove_subscription_cleans_all_platforms(self) -> None:
        """Verifies removal cleans up caches across platforms when
        platform=None.
        """
        self.store.add_subscription(
            "c910335", 111, 222, "msg", "", False, platform="threads"
        )
        self.store.add_subscription(
            "c910335", 111, 222, "msg", "", False, platform="instagram"
        )
        self.store.seen_posts["threads:c910335"] = ["p1"]
        self.store.seen_posts["instagram:c910335"] = ["p2"]
        self.store.display_names["threads:c910335"] = "達人1"
        self.store.display_names["instagram:c910335"] = "達人2"
        self.store.remove_subscription("c910335", 111)
        self.assertNotIn("threads:c910335", self.store.seen_posts)
        self.assertNotIn("instagram:c910335", self.store.seen_posts)
        self.assertNotIn("threads:c910335", self.store.display_names)
        self.assertNotIn("instagram:c910335", self.store.display_names)

    def test_remove_subscription_fail_if_not_present(self) -> None:
        """Verifies removing subscription fails if it does not exist."""
        removed = self.store.remove_subscription("c910335", 111)
        self.assertFalse(removed)

    def test_seen_posts_cache_lifecycle(self) -> None:
        """Verifies checking, caching, and loading state of seen posts."""
        # 1. Unknown user/post should return false and not raise exception
        self.assertFalse(self.store.is_post_seen("c910335", "post1"))

        # 2. Initialize seen cache
        self.store.init_user_seen_posts("c910335", ["post1", "post2"])
        self.assertTrue(self.store.is_post_seen("c910335", "post1"))
        self.assertFalse(self.store.is_post_seen("c910335", "post3"))

        # 3. Add single post to seen cache
        self.store.mark_post_seen("c910335", "post3")
        self.assertTrue(self.store.is_post_seen("c910335", "post3"))

        # 4. Mark post seen for a brand new user not yet in seen_posts dict
        self.store.mark_post_seen("newuser", "postA")
        self.assertTrue(self.store.is_post_seen("newuser", "postA"))

    def test_display_name_caching(self) -> None:
        """Verifies getting, updating, and loading display names."""
        # Default name when uncached is username itself
        self.assertEqual(self.store.get_display_name("c910335"), "c910335")

        # Update cache
        self.store.update_display_name("c910335", "達人")
        self.assertEqual(self.store.get_display_name("c910335"), "達人")

        # Verify it loads display names from JSON file on disk
        new_store = data.DataStore()
        self.assertEqual(new_store.get_display_name("c910335"), "達人")

    def test_get_subscriptions_for_user(self) -> None:
        """Verifies retrieving subscriptions matching a username."""
        self.store.add_subscription("c910335", 111, 222, "msg", "", False)
        self.store.add_subscription("c910335", 333, 222, "msg", "", False)
        self.store.add_subscription("otheruser", 111, 222, "msg", "", False)

        subs = self.store.get_subscriptions_for_user("c910335")
        self.assertEqual(len(subs), 2)

    def test_save_failures_dont_crash(self) -> None:
        """Verifies save failures in databases don't raise exceptions."""
        with mock.patch.object(
            self.store, "_safe_write", side_effect=OSError("Disk Full")
        ):
            # These should catch and print without raising exceptions
            self.store.save_subscriptions()
            self.store.save_seen_posts()
            self.store.save_display_names()

    def test_get_all_sub_usernames(self) -> None:
        """Verifies retrieval of all unique subscribed usernames."""
        self.store.add_subscription("userA", 111, 222, "msg", "", False)
        self.store.add_subscription("userB", 333, 222, "msg", "", False)
        self.store.add_subscription("usera", 444, 222, "msg", "", False)
        usernames = self.store.get_all_sub_usernames()
        self.assertEqual(usernames, {"usera", "userb"})

    def test_get_data_store(self) -> None:
        """Verifies get_data_store returns the DataStore singleton instance."""
        ds = data.get_data_store()
        self.assertIsInstance(ds, data.DataStore)

    def test_instagram_subscription_lifecycle(self) -> None:
        """Verifies full subscription and cache lifecycle for Instagram."""
        self.store.add_subscription(
            username="nasa",
            channel_id=111,
            server_id=222,
            message="NASA IG: {url}",
            mention="",
            overwrite=False,
            include_media=True,
            platform="instagram",
        )
        subs = self.store.list_subscriptions(111)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["platform"], "instagram")
        self.assertEqual(subs[0]["username"], "nasa")

        # Check unique targets
        targets = self.store.get_unique_targets()
        self.assertIn(("instagram", "nasa"), targets)

        # Check seen posts and display names isolation
        self.assertFalse(
            self.store.has_seen_posts_entry("nasa", platform="instagram")
        )
        self.store.init_user_seen_posts(
            "nasa", ["ig_post_1"], platform="instagram"
        )
        self.assertTrue(
            self.store.has_seen_posts_entry("nasa", platform="instagram")
        )
        self.assertTrue(
            self.store.is_post_seen("nasa", "ig_post_1", platform="instagram")
        )
        self.assertFalse(
            self.store.is_post_seen("nasa", "ig_post_2", platform="instagram")
        )
        self.store.mark_post_seen("nasa", "ig_post_2", platform="instagram")
        self.assertTrue(
            self.store.is_post_seen("nasa", "ig_post_2", platform="instagram")
        )

        self.store.update_display_name(
            "nasa", "NASA Official", platform="instagram"
        )
        self.assertEqual(
            self.store.get_display_name("nasa", platform="instagram"),
            "NASA Official",
        )
        # Threads display name should still default to username
        self.assertEqual(
            self.store.get_display_name("nasa", platform="threads"),
            "nasa",
        )

        # Removal cleans up caches
        removed = self.store.remove_subscription(
            "nasa", 111, platform="instagram"
        )
        self.assertTrue(removed)
        self.assertNotIn("instagram:nasa", self.store.seen_posts)
        self.assertNotIn("instagram:nasa", self.store.display_names)

    def test_cache_key_resolution(self) -> None:
        """Verifies _get_cache_key formats correctly across platforms."""
        self.assertEqual(
            self.store._get_cache_key("c910335", "threads"),
            "threads:c910335",
        )
        self.assertEqual(
            self.store._get_cache_key("c910335", "instagram"),
            "instagram:c910335",
        )

    def test_remove_subscription_with_platform_filter(self) -> None:
        """Verifies platform filtering when removing subscriptions."""
        self.store.add_subscription(
            "multiuser", 111, 222, "msg", "", False, platform="threads"
        )
        self.store.add_subscription(
            "multiuser", 111, 222, "msg", "", False, platform="instagram"
        )
        self.assertEqual(len(self.store.list_subscriptions(111)), 2)

        # Remove only Instagram
        self.assertTrue(
            self.store.remove_subscription(
                "multiuser", 111, platform="instagram"
            )
        )
        remaining = self.store.list_subscriptions(111)
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["platform"], "threads")

    def test_load_legacy_data_backfills_platform(self) -> None:
        """Verifies load() backfills platform: threads for legacy data."""
        legacy_data = [
            {
                "username": "legacy_user",
                "channel_id": 111,
                "server_id": 222,
                "message": "legacy msg",
                "mention": "",
                "include_media": False,
            }
        ]
        with open(self.store.DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(legacy_data, f)

        self.store.load()
        subs = self.store.list_subscriptions(111)
        self.assertEqual(len(subs), 1)
        self.assertEqual(subs[0]["platform"], data.Platform.THREADS.value)

    def test_safe_write_cleans_up_temp_on_serialization_failure(self) -> None:
        """Verifies _safe_write removes temp files on serialization failure."""
        target_file = os.path.join(self.test_dir, "fail.json")
        initial_files = set(os.listdir(self.test_dir))

        with self.assertRaises(TypeError):
            self.store._safe_write(target_file, object())

        current_files = set(os.listdir(self.test_dir))
        self.assertEqual(initial_files, current_files)

    def test_add_subscription_normalizes_platform(self) -> None:
        """Verifies add_subscription normalizes platform casing and enum."""
        self.assertTrue(
            self.store.add_subscription(
                "nasa",
                111,
                222,
                "msg",
                "",
                False,
                platform="Instagram",
            )
        )
        sub = self.store.list_subscriptions(111)[0]
        self.assertEqual(sub["platform"], "instagram")

        # Overwrite with Platform enum
        self.assertTrue(
            self.store.add_subscription(
                "nasa",
                111,
                222,
                "updated msg",
                "",
                True,
                platform=data.Platform.INSTAGRAM,
            )
        )
        updated = self.store.list_subscriptions(111)[0]
        self.assertEqual(updated["platform"], "instagram")
        self.assertEqual(updated["message"], "updated msg")


if __name__ == "__main__":
    unittest.main()
