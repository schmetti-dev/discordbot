"""
Buchclub Discord Bot — Einstiegspunkt

Startet den Bot, lädt alle Cogs und registriert Slash Commands.
"""

import asyncio
import os
import logging

import discord
from discord.ext import commands
from dotenv import load_dotenv

from database import Database

# Logging einrichten
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("buchclub")

# .env laden
load_dotenv()

# Intents — welche Discord-Events der Bot empfangen darf
intents = discord.Intents.default()
intents.message_content = True  # Für zukünftige Prefix-Erweiterungen


class BuchclubBot(commands.Bot):
    """Haupt-Bot-Klasse mit Lebenszyklus-Management."""

    def __init__(self):
        super().__init__(
            command_prefix="!",  # Fallback, wir nutzen primär Slash Commands
            intents=intents,
            help_command=None,
        )
        self.db: Database | None = None

    async def setup_hook(self) -> None:
        """Wird einmalig beim Start aufgerufen — Datenbank + Cogs laden."""
        # Datenbank initialisieren
        self.db = Database("buchclub.db")
        await self.db.setup()
        log.info("Datenbank initialisiert.")

        # Cogs laden
        await self.load_extension("cogs.books")
        await self.load_extension("cogs.progress")
        log.info("Cogs geladen.")

        # Slash Commands synchronisieren
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            # Entwicklungsmodus: nur auf einem Server (sofort aktiv)
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info(f"Slash Commands auf Guild {guild_id} synchronisiert.")
        else:
            # Produktivmodus: global (bis zu 1h Verzögerung)
            await self.tree.sync()
            log.info("Slash Commands global synchronisiert.")

    async def on_ready(self) -> None:
        """Wird aufgerufen wenn der Bot verbunden und bereit ist."""
        log.info(f"✅ Bot bereit als {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.reading,
                name="im Buchclub 📚",
            )
        )


async def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise ValueError("DISCORD_TOKEN nicht in .env gesetzt!")

    bot = BuchclubBot()
    async with bot:
        await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
