"""
Cog: Achievements

Commands:
    /achievements — deine Achievements, dein Rang und der Weg zur nächsten Stufe

Achievements sind privat. Jedes Mitglied sieht nur die eigenen, und zwar nur
in Antworten, die nur es selbst sieht (ephemeral). Der Bot postet sie nirgends,
und niemand kann die Achievements eines anderen abrufen.

Freischaltungen, die nicht aus einem eigenen Befehl kommen (Beiträge in einem
Buch-Thread, das letzte Mitglied beendet ein Buch), warten als ungesehen und
erscheinen beim nächsten /fortschritt oder /achievements.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from cogs.goals import club_timezone
from services.achievements import badge_file, earned, event_unlocks, next_rank, overview, rank_for, unlock_text, unlock_title
from services.goals import progress_in_unit

log = logging.getLogger("buchclub.achievements")

BADGES = Path(__file__).resolve().parent.parent / "assets" / "badges"
CREDIT = "Abzeichen-Icons: game-icons.net (CC BY 3.0)"
EMBED_COLOR = 0xD9A12B
MAX_EMBEDS = 10  # Discord erlaubt höchstens zehn Embeds pro Nachricht


async def check_member(db, user_id: int, guild_id: int, events: set[str] = frozenset(),
                       unlocked_at: str | None = None) -> list[tuple[str, int]]:
    """Was die Kennzahlen jetzt hergeben, speichern; nur Neues zurückgeben."""
    stats = await db.achievement_stats(user_id, guild_id)
    items = earned(stats) | {(key, 0) for key in events}
    return await db.store_achievements(user_id, guild_id, items, unlocked_at)


def unlock_messages(unlocks: list[tuple[str, int]], stats: dict) -> list[tuple[list[discord.Embed], list[discord.File]]]:
    """Freischaltungen als Nachrichten mit je höchstens zehn Embeds und ihren Abzeichen."""
    messages = []
    for start in range(0, len(unlocks), MAX_EMBEDS):
        embeds, files, names = [], [], set()
        for key, tier in unlocks[start:start + MAX_EMBEDS]:
            name = badge_file(key, tier)
            embed = discord.Embed(title=f"🏆 {unlock_title(key, tier)}", description=unlock_text(key, tier, stats), color=EMBED_COLOR)
            if (BADGES / name).exists():
                embed.set_thumbnail(url=f"attachment://{name}")
                if name not in names:
                    files.append(discord.File(BADGES / name, filename=name))
                    names.add(name)
            embeds.append(embed)
        embeds[-1].set_footer(text="Nur du siehst das. · " + CREDIT)
        messages.append((embeds, files))
    return messages


async def show_unseen(interaction: discord.Interaction, db) -> int:
    """Ungesehene Freischaltungen nur dem Mitglied selbst zeigen. Gibt die Anzahl zurück."""
    unseen = await db.get_unseen(interaction.user.id, interaction.guild_id)
    if not unseen:
        return 0
    stats = await db.achievement_stats(interaction.user.id, interaction.guild_id)
    for embeds, files in unlock_messages(unseen, stats):
        await interaction.followup.send(embeds=embeds, files=files, ephemeral=True)
    await db.mark_seen(interaction.user.id, interaction.guild_id)
    return len(unseen)


async def after_progress(bot, interaction: discord.Interaction, previous: dict | None, isbn: str,
                         current_book: dict | None, completed: bool) -> None:
    """
    Nach einem /fortschritt: Ereignisse auswerten, erreichte Ziele festhalten,
    Achievements prüfen und dem Mitglied privat zeigen. Ein Fehler hier darf
    den Eintrag selbst nicht kaputt machen, deshalb wird er nur geloggt.
    """
    db = bot.db
    user_id, guild_id = interaction.user.id, interaction.guild_id
    try:
        new = await db.get_progress(user_id, guild_id, isbn)
        record = await db.get_book_record(isbn)
        book = current_book if current_book and current_book["isbn"] == isbn else record
        now = datetime.now(timezone.utc)
        local = now.astimezone(club_timezone())
        events = event_unlocks(previous, new, book, local, now, is_club_book=record is not None)

        goal = await db.get_goal(user_id, guild_id, isbn)
        if goal:
            value = progress_in_unit(new, goal["unit"], book)
            if value is not None and value >= goal["target"]:
                await db.record_goal_reached(user_id, guild_id, isbn, goal["target"], goal["deadline"], local.date().isoformat())

        await check_member(db, user_id, guild_id, events)

        # Wer ein Clubbuch beendet, kann anderen "Einer für alle" freischalten. Die sehen es später.
        if completed and record:
            for reader in await db.book_readers(guild_id, isbn):
                if reader != user_id:
                    await check_member(db, reader, guild_id)

        await show_unseen(interaction, db)
    except Exception:
        log.exception("Achievements nach /fortschritt fehlgeschlagen.")


def should_count(channel_id: int, author_is_bot: bool, thread_ids: set[int]) -> bool:
    """Plaudertasche zählt nur Beiträge von Menschen in Threads von Clubbüchern."""
    return not author_is_bot and channel_id in thread_ids


class Achievements(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="achievements", description="Deine Achievements und dein Rang. Nur du siehst sie.")
    async def achievements(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        db = self.bot.db
        user_id, guild_id = interaction.user.id, interaction.guild_id
        await check_member(db, user_id, guild_id)

        stats = await db.achievement_stats(user_id, guild_id)
        unlocked = await db.get_achievements(user_id, guild_id)
        rank, color = rank_for(stats["books_finished"])
        following = next_rank(stats["books_finished"])
        description = f"Rang: **{rank}**"
        if following:
            name, missing = following
            description += f"\nNoch {missing} {'Buch' if missing == 1 else 'Bücher'} bis „{name}“"

        embed = discord.Embed(title=f"🏆 Achievements von {interaction.user.display_name}", description=description, color=color)
        for title, text in overview(stats, unlocked):
            embed.add_field(name=title, value=text, inline=False)
        embed.set_footer(text="Nur du siehst das. · " + CREDIT)
        await interaction.followup.send(embed=embed, ephemeral=True)
        await show_unseen(interaction, db)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        try:
            thread_ids = await self.bot.db.book_thread_ids()
            if not should_count(message.channel.id, message.author.bot, thread_ids):
                return
            await self.bot.db.add_thread_message(message.author.id, message.guild.id)
            await check_member(self.bot.db, message.author.id, message.guild.id)
        except Exception:
            log.exception("Beitrag im Buch-Thread nicht gezählt.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Achievements(bot))
