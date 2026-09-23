"""Unit tests for NotifyBot main discord client wrapper."""

# pylint: disable=protected-access

import unittest
from unittest import mock

import discord

import bot


class NotifyBotTest(unittest.IsolatedAsyncioTestCase):
    """Test cases for NotifyBot subclassed client."""

    def test_init(self) -> None:
        """Verifies bot initializes with default intents."""
        bot_instance = bot.NotifyBot()
        self.assertIsInstance(bot_instance.intents, discord.Intents)

    async def test_setup_hook(self) -> None:
        """Verifies setup_hook registers extensions and starts browser."""
        bot_instance = bot.NotifyBot()
        bot_instance.load_extension = mock.AsyncMock()
        bot_instance.tree.sync = mock.AsyncMock()

        with mock.patch(
            "browser.Browser.start", new_callable=mock.AsyncMock
        ) as mock_start:
            await bot_instance.setup_hook()
            mock_start.assert_called_once()

        # Should load the commands and monitor extension cogs
        bot_instance.load_extension.assert_any_call("cogs.commands")
        bot_instance.load_extension.assert_any_call("cogs.monitor")
        self.assertEqual(bot_instance.load_extension.call_count, 2)
        bot_instance.tree.sync.assert_called_once()

    async def test_close(self) -> None:
        """Verifies close() shuts down client and stops browser."""
        bot_instance = bot.NotifyBot()
        with mock.patch(
            "browser.Browser.close", new_callable=mock.AsyncMock
        ) as mock_close:
            with mock.patch(
                "discord.ext.commands.Bot.close", new_callable=mock.AsyncMock
            ) as mock_super_close:
                await bot_instance.close()
                mock_close.assert_called_once()
                mock_super_close.assert_called_once()

    async def test_on_ready(self) -> None:
        """Verifies on_ready event prints logging information."""
        bot_instance = bot.NotifyBot()
        # Mock user object
        mock_user = mock.MagicMock()
        mock_user.__str__ = mock.Mock(return_value="NotifyBot")
        mock_user.id = 12345
        bot_instance._connection.user = mock_user

        with mock.patch("builtins.print") as mock_print:
            await bot_instance.on_ready()
            mock_print.assert_called_once_with(
                "Logged in as NotifyBot (ID: 12345)"
            )


if __name__ == "__main__":
    unittest.main()
