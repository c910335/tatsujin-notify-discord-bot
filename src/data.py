"""Data persistence management for subscriptions and seen post cache."""

import json
import os
import tempfile
import threading
from enum import StrEnum
from typing import Any, TypedDict


class Platform(StrEnum):
    """Supported social media platforms."""

    THREADS = "threads"
    INSTAGRAM = "instagram"


class SubscriptionDict(TypedDict):
    """Specific schema for a Discord channel subscription to a user."""

    username: str
    channel_id: int
    server_id: int | None
    message: str
    mention: str
    include_media: bool
    platform: str


class PostDict(TypedDict):
    """Specific schema for a parsed social media post."""

    id: str
    code: str
    username: str
    display_name: str
    text: str
    timestamp: int
    url: str | None
    media_urls: list[str]


class DataStore:
    """Thread-safe file persistence manager for subscriptions and seen posts."""

    DATA_FILE = "data.json"
    SEEN_FILE = "seen_posts.json"
    DISPLAY_NAMES_FILE = "display_names.json"

    def __init__(self) -> None:
        """Initializes the locks and internal storage caches."""
        self.lock = threading.RLock()
        self.subscriptions: list[SubscriptionDict] = []
        self.seen_posts: dict[str, list[str]] = {}
        # Cache of username -> display_name from last scrape
        self.display_names: dict[str, str] = {}
        self.load()

    def load(self) -> None:
        """Loads subscriptions and seen posts cache from disk."""
        with self.lock:
            # Load Subscriptions
            if os.path.exists(self.DATA_FILE):
                try:
                    with open(self.DATA_FILE, "r", encoding="utf-8") as f:
                        self.subscriptions = json.load(f)
                    for s in self.subscriptions:
                        if isinstance(s, dict) and "platform" not in s:
                            s["platform"] = Platform.THREADS.value
                except (
                    json.JSONDecodeError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as e:
                    print(f"Error loading subscriptions: {e}")
                    self.subscriptions = []
            else:
                self.subscriptions = []

            # Load Seen Posts Cache
            if os.path.exists(self.SEEN_FILE):
                try:
                    with open(self.SEEN_FILE, "r", encoding="utf-8") as f:
                        self.seen_posts = json.load(f)
                except (
                    json.JSONDecodeError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as e:
                    print(f"Error loading seen posts cache: {e}")
                    self.seen_posts = {}
            else:
                self.seen_posts = {}

            # Load Display Names Cache
            if os.path.exists(self.DISPLAY_NAMES_FILE):
                try:
                    with open(
                        self.DISPLAY_NAMES_FILE, "r", encoding="utf-8"
                    ) as f:
                        self.display_names = json.load(f)
                except (
                    json.JSONDecodeError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as e:
                    print(f"Error loading display names cache: {e}")
                    self.display_names = {}
            else:
                self.display_names = {}

    def _safe_write(self, filepath: str, data: Any) -> None:
        """Atomically writes data to a file via a temporary file.

        Args:
            filepath: The destination file path.
            data: The JSON serializable data to write.

        Raises:
            OSError: If temporary directory is unwritable or replacement fails.
            TypeError: If data is not JSON serializable.
            ValueError: If JSON encoding fails.
        """
        dir_name = os.path.dirname(os.path.abspath(filepath))
        temp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", dir=dir_name, delete=False, encoding="utf-8"
            ) as tf:
                temp_path = tf.name
                json.dump(data, tf, indent=2, ensure_ascii=False)
                tf.flush()
                os.fsync(tf.fileno())
            os.replace(temp_path, filepath)
        except Exception:  # pylint: disable=broad-except
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
            raise

    def save_subscriptions(self) -> None:
        """Saves current subscriptions to data.json."""
        with self.lock:
            try:
                self._safe_write(self.DATA_FILE, self.subscriptions)
                print("Subscriptions data saved.")
            except (OSError, TypeError, ValueError) as e:
                print(f"Failed to save subscriptions: {e}")

    def save_seen_posts(self) -> None:
        """Saves current seen posts cache to seen_posts.json."""
        with self.lock:
            try:
                self._safe_write(self.SEEN_FILE, self.seen_posts)
                print("Seen posts data saved.")
            except (OSError, TypeError, ValueError) as e:
                print(f"Failed to save seen posts: {e}")

    def save_display_names(self) -> None:
        """Saves current display names cache to display_names.json."""
        with self.lock:
            try:
                self._safe_write(self.DISPLAY_NAMES_FILE, self.display_names)
                print("Display names data saved.")
            except (OSError, TypeError, ValueError) as e:
                print(f"Failed to save display names: {e}")

    def _get_cache_key(
        self, username: str, platform: str | Platform = Platform.THREADS
    ) -> str:
        """Computes the internal cache key for seen posts and display names.

        Args:
            username: The profile username.
            platform: The platform name.

        Returns:
            The normalized cache key string in '{platform}:{username}' format.
        """
        username_clean = username.strip().lower()
        platform_clean = str(platform).strip().lower()
        return f"{platform_clean}:{username_clean}"

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def add_subscription(
        self,
        username: str,
        channel_id: int,
        server_id: int | None,
        message: str,
        mention: str,
        overwrite: bool,
        include_media: bool = False,
        platform: str | Platform = Platform.THREADS,
    ) -> bool:
        """Adds or updates a channel subscription to a user.

        Args:
            username: The profile username.
            channel_id: The Discord channel ID.
            server_id: The Discord guild ID, or None for DMs.
            message: The notification template message.
            mention: The mention role or user string.
            overwrite: Whether to overwrite existing subscription settings.
            include_media: Whether to include images/videos in notifications.
            platform: Social platform (Platform.THREADS or Platform.INSTAGRAM).

        Returns:
            True if the subscription was successfully created or updated,
            False otherwise.
        """
        username = username.strip().lower()
        platform_str = str(platform).strip().lower()

        with self.lock:
            # Check if already subscribed in this channel for this platform
            existing = None
            for sub in self.subscriptions:
                if (
                    sub["platform"] == platform_str
                    and sub["username"] == username
                    and sub["channel_id"] == channel_id
                ):
                    existing = sub
                    break

            if existing:
                if not overwrite:
                    return False
                # Update existing
                existing["message"] = message
                existing["mention"] = mention
                existing["server_id"] = server_id
                existing["include_media"] = include_media
                existing["platform"] = platform_str
            else:
                # Create new
                self.subscriptions.append(
                    {
                        "username": username,
                        "channel_id": channel_id,
                        "server_id": server_id,
                        "message": message,
                        "mention": mention,
                        "include_media": include_media,
                        "platform": platform_str,
                    }
                )

            self.save_subscriptions()
            return True

    def remove_subscription(
        self,
        username: str,
        channel_id: int,
        platform: str | None = None,
    ) -> bool:
        """Removes a channel subscription to a user.

        Args:
            username: The profile username.
            channel_id: The Discord channel ID.
            platform: Optional platform filter. If None, removes matching
                subscription regardless of platform.

        Returns:
            True if the subscription was successfully removed, False otherwise.
        """
        username = username.strip().lower()
        if platform:
            platform = platform.strip().lower()

        with self.lock:
            original_len = len(self.subscriptions)
            self.subscriptions = [
                sub
                for sub in self.subscriptions
                if not (
                    sub["username"] == username
                    and sub["channel_id"] == channel_id
                    and (platform is None or sub["platform"] == platform)
                )
            ]

            if len(self.subscriptions) < original_len:
                self.save_subscriptions()

                # Clean up metadata if no channels subscribe to this target
                platforms_to_check = (
                    [Platform.THREADS.value, Platform.INSTAGRAM.value]
                    if platform is None
                    else [str(platform)]
                )
                for p in platforms_to_check:
                    remaining = [
                        s
                        for s in self.subscriptions
                        if s["username"] == username and s["platform"] == p
                    ]
                    if not remaining:
                        key = self._get_cache_key(username, p)
                        if key in self.seen_posts:
                            del self.seen_posts[key]
                            self.save_seen_posts()
                        if key in self.display_names:
                            del self.display_names[key]
                            self.save_display_names()

                return True
            return False

    def list_subscriptions(self, channel_id: int) -> list[SubscriptionDict]:
        """Lists all subscriptions active for a specific channel ID.

        Args:
            channel_id: The Discord channel ID.

        Returns:
            A list of matching subscription dictionaries.
        """
        return [
            sub for sub in self.subscriptions if sub["channel_id"] == channel_id
        ]

    def get_unique_targets(self) -> set[tuple[str, str]]:
        """Gets the set of unique (platform, username) pairs subscribed to.

        Returns:
            A set of (platform, lowercase username) tuples.
        """
        return {
            (sub["platform"], sub["username"]) for sub in self.subscriptions
        }

    def get_all_sub_usernames(self) -> set[str]:
        """Gets the set of all unique usernames currently subscribed to.

        Returns:
            A set of lowercase username strings.
        """
        return {sub["username"] for sub in self.subscriptions}

    def get_subscriptions_for_user(
        self, username: str, platform: str | None = None
    ) -> list[SubscriptionDict]:
        """Gets all subscription objects targeting a specific user.

        Args:
            username: The profile username.
            platform: Optional platform filter.

        Returns:
            A list of subscription dictionaries.
        """
        username_clean = username.strip().lower()
        return [
            sub
            for sub in self.subscriptions
            if sub["username"] == username_clean
            and (platform is None or sub["platform"] == platform)
        ]

    # Seen posts helpers
    def has_seen_posts_entry(
        self, username: str, platform: str | Platform = Platform.THREADS
    ) -> bool:
        """Checks if a target user has an entry in seen posts cache.

        Args:
            username: The profile username.
            platform: The platform ("threads" or "instagram").

        Returns:
            True if the target has an initialized seen posts list, False
            otherwise.
        """
        key = self._get_cache_key(username, platform)
        return key in self.seen_posts

    def is_post_seen(
        self,
        username: str,
        post_id: str,
        platform: str | Platform = Platform.THREADS,
    ) -> bool:
        """Checks if a post ID has already been recorded in seen posts cache.

        Args:
            username: The profile username.
            post_id: The post ID to check.
            platform: The platform ("threads" or "instagram").

        Returns:
            True if the post has been processed, False otherwise.
        """
        key = self._get_cache_key(username, platform)
        return post_id in self.seen_posts.get(key, [])

    def mark_post_seen(
        self,
        username: str,
        post_id: str,
        platform: str | Platform = Platform.THREADS,
    ) -> None:
        """Marks a post ID as processed/seen in the cache.

        Args:
            username: The profile username.
            post_id: The post ID.
            platform: The platform ("threads" or "instagram").
        """
        with self.lock:
            key = self._get_cache_key(username, platform)
            if key not in self.seen_posts:
                self.seen_posts[key] = []
            if post_id not in self.seen_posts[key]:
                self.seen_posts[key].append(post_id)
                self.save_seen_posts()

    def init_user_seen_posts(
        self,
        username: str,
        post_ids: list[str],
        platform: str | Platform = Platform.THREADS,
    ) -> None:
        """Initializes the seen posts cache for a newly added target.

        Args:
            username: The profile username.
            post_ids: The list of pre-existing post IDs.
            platform: The platform ("threads" or "instagram").
        """
        with self.lock:
            key = self._get_cache_key(username, platform)
            if key not in self.seen_posts:
                self.seen_posts[key] = list(post_ids)
                self.save_seen_posts()

    # Display name cache
    def update_display_name(
        self,
        username: str,
        display_name: str,
        platform: str | Platform = Platform.THREADS,
    ) -> None:
        """Updates the cached display name of a profile.

        Args:
            username: The profile username.
            display_name: The display name text.
            platform: The platform ("threads" or "instagram").
        """
        with self.lock:
            key = self._get_cache_key(username, platform)
            if self.display_names.get(key) != display_name:
                self.display_names[key] = display_name
                self.save_display_names()

    def get_display_name(
        self, username: str, platform: str | Platform = Platform.THREADS
    ) -> str:
        """Gets the cached display name or falls back to the username itself.

        Args:
            username: The profile username.
            platform: The platform ("threads" or "instagram").

        Returns:
            The cached display name, or the username on cache miss.
        """
        key = self._get_cache_key(username, platform)
        return self.display_names.get(key, username)


_db = DataStore()


def get_data_store() -> DataStore:
    """Returns the global DataStore singleton instance.

    Returns:
        The thread-safe DataStore singleton instance.
    """
    return _db
