# Tatsujin's Notify Discord Bot

[![Python Unit Tests and Coverage](https://github.com/c910335/tatsujin-notify-discord-bot/actions/workflows/python-tests.yml/badge.svg)](https://github.com/c910335/tatsujin-notify-discord-bot/actions/workflows/python-tests.yml)

A Discord bot for [Threads](https://www.threads.com) and [Instagram](https://www.instagram.com) profile post notifications.

## Installation

1. Create an application on the [Discord Developer Portal](https://discord.com/developers/applications/) with the following configuration.

- Installation:
  - Default Install Settings:
    - Guild Install
      - Scopes: `bot`
      - Permissions: `Send Messages`

2. Clone this repository.

```sh
git clone https://github.com/c910335/tatsujin-notify-discord-bot.git
cd tatsujin-notify-discord-bot
```

3. Initialize virtual environment and install dependencies.

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Note: If you are running on Linux (e.g. Arch Linux), you may need to install additional system dependencies required by Chromium:
```sh
sudo pacman -S --needed nspr nss atk at-spi2-core libxcomposite libxdamage libxrandr libxkbcommon
```

4. Configure environment variables.

Create a `.env` file in the project root directory and populate your configuration settings:

```env
TNDB_DISCORD_TOKEN=YOUR_DISCORD_TOKEN_HERE
TNDB_ADMIN_CHANNEL_ID=0
TNDB_HEARTBEAT_DELAY_SECONDS=300
TNDB_HEARTBEAT_JITTER_SECONDS=30.0
TNDB_CHECK_DELAY_SECONDS=5
TNDB_CHECK_JITTER_SECONDS=2.5
TNDB_INSTAGRAM_CHECK_INTERVAL_SECONDS=1200
TNDB_INSTAGRAM_MAX_COOLDOWN_SECONDS=43200
```

## Usage

1. Run the bot.

```sh
python src/main.py
```

2. Invite the bot to your server using the installation link generated from the [Discord Developer Portal](https://discord.com/developers/applications/).

3. Use the slash commands in your server.

## Commands

All commands are restricted to server administrators. Target input accepts usernames (e.g. `c910335`, `snackssion.ig`) or full profile / post URLs (e.g. `https://www.threads.net/@c910335`, `https://www.instagram.com/snackssion.ig/`). When a URL is provided, the platform is automatically detected.

- `/subscribe`: Subscribe to a Threads or Instagram user profile for the current channel.
  - `username` (String): The username or profile URL (e.g. `https://www.threads.net/@c910335` or `https://www.instagram.com/snackssion.ig/`).
  - `message` (String): The message template to send when the user posts.
    Supports `{name}`, `{text}`, `{preview_text}`, `{quoted_text}`,
    `{quoted_preview_text}`, `{url}`, and `{mention}`. Autocomplete
    templates are available.
  - `mention` (Mentionable, Optional): The user or role to notify.
    If the template does not explicitly include `{mention}`, it will be
    prepended automatically.
  - `overwrite` (Boolean, Optional): Whether to overwrite an existing
    subscription (defaults to `False`).
  - `include_media` (Boolean, Optional): Whether to include post images/videos
    in notifications (defaults to `False`).
  - `platform` (Choice, Optional): `threads` or `instagram` (defaults to
    `threads`, automatically detected if a URL is provided).
- `/unsubscribe`: Unsubscribe from a profile for the current channel.
  - `username` (String): The username or URL to unsubscribe from.
  - `platform` (Choice, Optional): Optional platform filter (`threads` or `instagram`).
- `/test`: Trigger a test notification to the current channel.
  - `username` (String): The username or profile URL to send a test notification for.
  - `silent` (Boolean): If true, the test notification will be visible only to
    you (ephemeral).
  - `platform` (Choice, Optional): Optional platform filter (`threads` or `instagram`).
- `/post`: Send a one-time test notification for a specific post.
  - `post_id` (String): The specific post ID/code or URL (e.g. `DH_eOgcSUww` or `https://www.instagram.com/p/C_ACjgVvIX4/`).
  - `message` (String): The message template to send. Supports `{name}`,
    `{text}`, `{preview_text}`, `{quoted_text}`, `{quoted_preview_text}`,
    `{url}`, and `{mention}`. Autocomplete templates are available.
  - `mention` (Mentionable, Optional): The user or role to notify.
  - `include_media` (Boolean, Optional): Whether to include post images/videos
    in notifications (defaults to `False`).
  - `silent` (Boolean, Optional): If true, the test notification will be
    visible only to you (ephemeral, defaults to `False`).
  - `platform` (Choice, Optional): `threads` or `instagram` (defaults to `threads`, auto-detected if a URL is given).
- `/list`: List active subscriptions for current channel (ephemeral, tagged with platform badges such as `[Threads]` and `[Instagram]`).

## Development

### Code Formatting & Style

This project uses `black` to format code and `isort` to sort imports.

To format code:
```sh
black src/ tests/
```

To sort and format imports:
```sh
isort src/ tests/
```

### Linting

This project uses `pylint` for static code analysis. To run the linter:
```sh
PYTHONPATH=src pylint src/ tests/
```

### Testing & Coverage

Run the unit test suite:

```sh
PYTHONPATH=src python -m unittest discover -s tests -p "*_test.py" -t .
```

To run tests with code coverage reporting:

```sh
PYTHONPATH=src coverage run --source=src -m unittest discover -s tests -p "*_test.py" -t .
coverage report -m
```

## Contributing

1. Fork it (<https://github.com/c910335/tatsujin-notify-discord-bot/fork>)
2. Create your feature branch (`git checkout -b my-new-feature`)
3. Commit your changes (`git commit -am 'Add some feature'`)
4. Push to the branch (`git push origin my-new-feature`)
5. Create a new Pull Request

## Contributors

- [Tatsujin Chin](https://github.com/c910335) - creator and maintainer
