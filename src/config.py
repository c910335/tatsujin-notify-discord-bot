"""Configuration settings for Tatsujin's Notify Discord Bot."""

import os
import sys

import dotenv

# Load .env file (skip loading during unit tests to ensure isolation)
if "unittest" not in sys.modules:
    dotenv.load_dotenv()

# Discord Bot Token
DISCORD_TOKEN = os.getenv("TNDB_DISCORD_TOKEN", "YOUR_DISCORD_TOKEN_HERE")

# Discord channel ID to report bot errors to (admin channel)
ADMIN_CHANNEL_ID = int(os.getenv("TNDB_ADMIN_CHANNEL_ID", "0"))

# How often to check for updates (in seconds)
HEARTBEAT_DELAY_SECONDS = int(os.getenv("TNDB_HEARTBEAT_DELAY_SECONDS", "300"))

# Maximum random jitter to add/subtract from heartbeat interval (in seconds)
HEARTBEAT_JITTER_SECONDS = float(
    os.getenv("TNDB_HEARTBEAT_JITTER_SECONDS", "30.0")
)

# Cooldown sleep between checking individual targets (in seconds)
CHECK_DELAY_SECONDS = float(os.getenv("TNDB_CHECK_DELAY_SECONDS", "5"))

# Maximum random jitter to add to check delay (in seconds)
CHECK_JITTER_SECONDS = float(os.getenv("TNDB_CHECK_JITTER_SECONDS", "2.5"))

# Check interval for Instagram profiles (in seconds) to avoid rate limits;
# also serves as the base cooldown duration for exponential backoff.
INSTAGRAM_CHECK_INTERVAL_SECONDS = int(
    os.getenv("TNDB_INSTAGRAM_CHECK_INTERVAL_SECONDS", "1200")
)

# Maximum cooldown cap for exponential backoff on Instagram rate limits
INSTAGRAM_MAX_COOLDOWN_SECONDS = int(
    os.getenv("TNDB_INSTAGRAM_MAX_COOLDOWN_SECONDS", "43200")
)

# Predefined message templates offered as autocomplete choices for /subscribe
NOTIFICATION_MESSAGE_TEMPLATES = (
    "{mention} {name} 發布了新貼文： {url}",
    "**{name}** 發文囉！{quoted_text}",
    "**{name}** 發文囉！\n{preview_text}",
    "{mention} **{name}**:\n{text}",
    "{mention} **{name}**:{quoted_preview_text}",
    "{text}",
)
