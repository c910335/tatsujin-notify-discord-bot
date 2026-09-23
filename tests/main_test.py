"""Unit tests for the main bot entry point execution flow."""

import unittest
from unittest import mock

import config
import main


class MainTest(unittest.TestCase):
    """Test cases for the bot main entry point script."""

    def test_main_missing_token(self) -> None:
        """Verifies that main exits with status 1 if token is missing."""
        # 1. Missing (empty) token
        with mock.patch.object(config, "DISCORD_TOKEN", ""):
            with mock.patch("sys.exit", side_effect=SystemExit) as mock_exit:
                with mock.patch("builtins.print"):
                    with self.assertRaises(SystemExit):
                        main.main()
                    mock_exit.assert_called_once_with(1)

        # 2. Sample/Default token
        with mock.patch.object(
            config, "DISCORD_TOKEN", "YOUR_DISCORD_TOKEN_HERE"
        ):
            with mock.patch("sys.exit", side_effect=SystemExit) as mock_exit:
                with mock.patch("builtins.print"):
                    with self.assertRaises(SystemExit):
                        main.main()
                    mock_exit.assert_called_once_with(1)

    def test_main_success(self) -> None:
        """Verifies main starts the bot with valid token."""
        mock_bot_instance = mock.MagicMock()
        mock_bot_instance.run = mock.MagicMock()

        with mock.patch.object(config, "DISCORD_TOKEN", "valid_token"):
            with mock.patch("bot.NotifyBot", return_value=mock_bot_instance):
                with mock.patch("sys.stdout.reconfigure") as mock_reconfig:
                    with mock.patch("builtins.print"):
                        main.main()
                        mock_reconfig.assert_called_once_with(
                            line_buffering=True
                        )
                        mock_bot_instance.run.assert_called_once_with(
                            "valid_token"
                        )


if __name__ == "__main__":
    unittest.main()
