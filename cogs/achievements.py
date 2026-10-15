"""
Cog: Achievements

Commands:
    /achievements        — deine Achievements, dein Rang und der Weg zur nächsten Stufe
    /achievement-teilen  — eines deiner Achievements mit allen teilen

Achievements sind privat. Jedes Mitglied sieht nur die eigenen, und zwar nur
in Antworten, die nur es selbst sieht (ephemeral). Öffentlich wird ein
Achievement nur, wenn das Mitglied es selbst teilt: per Knopf unter der
privaten Nachricht oder mit /achievement-teilen. Dann erscheint es einmal im
Thread des aktuellen Buchs. Niemand kann die Achievements eines anderen abrufen.

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
from services.achievements import (
    BY_KEY, RANK_KEY, RANKS, badge_file, earned, event_unlocks, next_rank, overview, rank_for, share_text, unlock_text,
    unlock_title,
)
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


def valid_achievement(key: str, tier: int) -> bool:
    if key == RANK_KEY:
        return 1 <= tier < len(RANKS)
    achievement = BY_KEY.get(key)
    if achievement is None:
        return False
    return 1 <= tier <= len(achievement.thresholds) if achievement.kind == "tiered" else tier == 0


SHARE_PATTERN = r"buchketiere:teilen:(?P<key>[a-z_]+):(?P<tier>[0-9]+)"


class ShareButton(discord.ui.DynamicItem[discord.ui.Button], template=SHARE_PATTERN):
    """
    Knopf unter einer privaten Freischaltung. Der custom_id trägt Achievement und
    Stufe, deshalb funktioniert der Knopf auch nach einem Neustart des Bots.
    """

    def __init__(self, key: str, tier: int) -> None:
        label = f"Teilen: {unlock_title(key, tier)}"
        super().__init__(discord.ui.Button(
            label=label if len(label) <= 80 else label[:79] + "…",
            emoji="📣",
            style=discord.ButtonStyle.secondary,
            custom_id=f"buchketiere:teilen:{key}:{tier}",
        ))
        self.key, self.tier = key, tier

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match, /):
        return cls(match["key"], int(match["tier"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        await share_achievement(interaction.client, interaction, self.key, self.tier)


def share_view(unlocks: list[tuple[str, int]]) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for key, tier in unlocks:
        view.add_item(ShareButton(key, tier))
    return view


async def share_target(bot, interaction: discord.Interaction):
    """Thread des aktuellen Buchs, sonst der Kanal, in dem geteilt wurde."""
    book = await bot.db.get_book()
    record = await bot.db.get_book_record(book["isbn"]) if book else None
    thread_id = record.get("thread_id") if record else None
    if thread_id:
        channel = bot.get_channel(thread_id)
        if channel is None:
            try:
                channel = await bot.fetch_channel(thread_id)
            except discord.HTTPException:
                channel = None
        if channel is not None:
            return channel
    return interaction.channel


async def share_achievement(bot, interaction: discord.Interaction, key: str, tier: int) -> bool:
    """
    Die einzige Stelle, an der ein Achievement öffentlich wird: nur auf Wunsch
    des Mitglieds, nur ein eigenes, nur einmal.
    """
    await interaction.response.defer(ephemeral=True)
    db = bot.db
    user_id, guild_id = interaction.user.id, interaction.guild_id
    if not valid_achievement(key, tier) or (key, tier) not in await db.get_achievements(user_id, guild_id):
        await interaction.followup.send("Dieses Achievement hast du (noch) nicht.", ephemeral=True)
        return False
    if not await db.claim_share(user_id, guild_id, key, tier):
        await interaction.followup.send("Das hast du schon geteilt.", ephemeral=True)
        return False

    stats = await db.achievement_stats(user_id, guild_id)
    embed = discord.Embed(
        title=f"🏆 {unlock_title(key, tier)}",
        description=share_text(key, tier, stats, interaction.user.mention),
        color=EMBED_COLOR,
    )
    embed.set_footer(text=CREDIT)
    name = badge_file(key, tier)
    files = []
    if (BADGES / name).exists():
        embed.set_thumbnail(url=f"attachment://{name}")
        files.append(discord.File(BADGES / name, filename=name))

    channel = await share_target(bot, interaction)
    try:
        await channel.send(embed=embed, files=files, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException:
        log.exception("Teilen fehlgeschlagen.")
        await db.release_share(user_id, guild_id, key, tier)
        await interaction.followup.send("Teilen hat nicht geklappt. Versuch es gleich nochmal.", ephemeral=True)
        return False
    await interaction.followup.send(f"📣 Geteilt in {channel.mention}.", ephemeral=True)
    return True


async def show_unseen(interaction: discord.Interaction, db) -> int:
    """Ungesehene Freischaltungen nur dem Mitglied selbst zeigen, mit Knopf zum Teilen."""
    unseen = await db.get_unseen(interaction.user.id, interaction.guild_id)
    if not unseen:
        return 0
    stats = await db.achievement_stats(interaction.user.id, interaction.guild_id)
    start = 0
    for embeds, files in unlock_messages(unseen, stats):
        view = share_view(unseen[start:start + len(embeds)])
        start += len(embeds)
        await interaction.followup.send(embeds=embeds, files=files, view=view, ephemeral=True)
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

    @app_commands.command(name="achievement-teilen", description="Teilt eines deiner Achievements mit allen im Thread des aktuellen Buchs.")
    @app_commands.describe(achievement="Welches du teilen willst (nur deine, noch nicht geteilten)")
    async def teilen(self, interaction: discord.Interaction, achievement: str) -> None:
        key, _, tier = achievement.partition(":")
        if not tier.isdigit():
            await interaction.response.send_message("Bitte eins aus der Vorschlagsliste wählen.", ephemeral=True)
            return
        await share_achievement(self.bot, interaction, key, int(tier))

    @teilen.autocomplete("achievement")
    async def teilen_vorschlaege(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        choices = []
        for key, tier in await self.bot.db.get_unshared(interaction.user.id, interaction.guild_id):
            if not valid_achievement(key, tier):
                continue
            title = unlock_title(key, tier)
            if current.lower() in title.lower():
                choices.append(app_commands.Choice(name=title[:100], value=f"{key}:{tier}"))
        return choices[:25]

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
    bot.add_dynamic_items(ShareButton)
    await bot.add_cog(Achievements(bot))
