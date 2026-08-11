#!/usr/bin/env python
"""Main entry point for the Threads Notification Discord Bot.

This script initializes configuration, reconfigures stdout buffering to
ensure real-time logs, and runs the Discord bot instance.
"""

import sys

import bot
import config


def main() -> None:
    """Main execution function for the bot."""
    sys.stdout.reconfigure(line_buffering=True)
    token = config.DISCORD_TOKEN
    if not token or token == "YOUR_DISCORD_TOKEN_HERE":
        print(
            "ERROR: DISCORD_TOKEN is not set in the environment or config.py.",
            file=sys.stderr,
        )
        print(
            "Please configure DISCORD_TOKEN before starting the bot.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Starting Threads Notification Discord Bot...")
    bot_instance = bot.ThreadsBot()
    bot_instance.run(token)


if __name__ == "__main__":  # pragma: no cover
    main()
