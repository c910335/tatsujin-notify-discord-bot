"""Main Discord Bot client setup and extension loader."""

import discord
from discord.ext import commands

import browser


class NotifyBot(commands.Bot):
    """Subclassed commands.Bot to load configuration and cogs."""

    def __init__(self) -> None:
        """Initializes the bot client with default intents."""
        intents = discord.Intents.default()
        super().__init__(command_prefix="!", intents=intents)
        self.browser = browser.Browser()

    async def setup_hook(self) -> None:
        """Loads all extension cogs and syncs slash commands globally."""
        await self.browser.start()

        await self.load_extension("cogs.commands")
        await self.load_extension("cogs.monitor")
        await self.tree.sync()
        print("Slash commands synced globally.")

    async def close(self) -> None:
        """Closes the bot connection and cleans up external resources."""
        await self.browser.close()
        await super().close()

    async def on_ready(self) -> None:
        """Handles bot ready event."""
        print(f"Logged in as {self.user} (ID: {self.user.id})")
