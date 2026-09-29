"""
Cog: Leseziele und Erinnerungen

Commands:
    /leseziel setzen   — Datum fürs ganze Buch, oder bis zu einer Seite / einem Kapitel
    /leseziel zeigen   — Was das Ziel heute bedeutet
    /leseziel loeschen — Ziel entfernen (die Erinnerung verschwindet mit)
    /erinnerung an     — Erinnerung einschalten (nur wer das tut, bekommt eine)
    /erinnerung aus    — Erinnerung ausschalten

Alles hier ist privat: Antworten sieht nur das Mitglied selbst, Erinnerungen
kommen als Direktnachricht und nie in einen Kanal.
"""

import logging
import os
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands, tasks

from services.goals import compute_pace, describe_pace, progress_in_unit, reminder_is_due, unit_label

log = logging.getLogger("buchclub.goals")

# Erinnerungen gehen nur tagsüber raus, in der Zeitzone des Clubs.
QUIET_BEFORE_HOUR = 9
QUIET_FROM_HOUR = 20


def club_timezone() -> ZoneInfo:
    return ZoneInfo(os.getenv("TZ", "Europe/Berlin"))


def parse_date(text: str) -> date | None:
    """Nimmt 31.10.2026 oder 2026-10-31."""
    for pattern in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), pattern).date()
        except ValueError:
            continue
    return None


async def send_due_reminders(db, send, now: datetime, today: date) -> int:
    """
    Schickt alle fälligen Erinnerungen über `send(user_id, text)` und gibt
    zurück, wie viele rausgingen. Ein Mitglied, das keine Direktnachrichten
    annimmt, hält die anderen nicht auf.
    """
    book = await db.get_book()
    if not book:
        return 0

    sent = 0
    for reminder in await db.get_reminders(book["isbn"]):
        user_id, guild_id = reminder["user_id"], reminder["guild_id"]
        goal = await db.get_goal(user_id, guild_id, book["isbn"])
        progress = await db.get_progress(user_id, guild_id, book["isbn"])
        current = progress_in_unit(progress, goal["unit"], book) if goal else None
        if not reminder_is_due(reminder, goal, current, now, today):
            continue

        pace = compute_pace(goal, current, today)
        text = (
            f"📚 Kleine Erinnerung an dein Leseziel für *{book['title']}*.\n"
            f"{describe_pace(goal, pace)}\n"
            f"Ausschalten kannst du das jederzeit mit `/erinnerung aus`."
        )
        try:
            await send(user_id, text)
            sent += 1
        except discord.Forbidden:
            log.info("Erinnerung nicht zustellbar: Mitglied nimmt keine Direktnachrichten an.")
        except discord.HTTPException as error:
            log.warning(f"Erinnerung nicht zustellbar: {error}")
            continue
        # Auch nach einer abgewiesenen Nachricht warten, statt stündlich neu zu klopfen.
        await db.mark_reminder_sent(user_id, guild_id, book["isbn"], now.isoformat())
    return sent


class Goals(commands.Cog):
    leseziel = app_commands.Group(name="leseziel", description="Dein persönliches Leseziel")
    erinnerung = app_commands.Group(name="erinnerung", description="Erinnerung an dein Leseziel")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.reminder_loop.start()

    async def cog_unload(self) -> None:
        self.reminder_loop.cancel()

    # ── /leseziel ─────────────────────────────────────────────────────────────

    @leseziel.command(name="setzen", description="Setzt dein Leseziel: ein Datum fürs ganze Buch oder bis zu einer Stelle.")
    @app_commands.describe(
        datum="Bis wann, z.B. 31.10.2026",
        bis_seite="Nur bis zu dieser Seite (sonst: das ganze Buch)",
        bis_kapitel="Nur bis zu diesem Kapitel (sonst: das ganze Buch)",
    )
    async def setzen(
        self,
        interaction: discord.Interaction,
        datum: str,
        bis_seite: app_commands.Range[int, 1] | None = None,
        bis_kapitel: app_commands.Range[int, 1] | None = None,
    ) -> None:
        async def reply(text: str) -> None:
            await interaction.response.send_message(text, ephemeral=True)

        if bis_seite is not None and bis_kapitel is not None:
            await reply("❌ Bitte nur `bis_seite` **oder** `bis_kapitel` angeben.")
            return

        deadline = parse_date(datum)
        today = datetime.now(club_timezone()).date()
        if deadline is None:
            await reply("❌ Das Datum habe ich nicht verstanden. Beispiel: `31.10.2026`")
            return
        if deadline < today:
            await reply("❌ Das Datum liegt in der Vergangenheit.")
            return

        book = await self.bot.db.get_book()
        if not book:
            await reply("❌ Kein Buch aktiv. Ein Admin kann mit `/buch-setzen` ein Buch festlegen.")
            return

        progress = await self.bot.db.get_progress(interaction.user.id, interaction.guild_id, book["isbn"])

        # Einheit und Ziel bestimmen. Ohne Angabe: das ganze Buch, in der Einheit,
        # in der das Mitglied seinen Stand führt, sonst in Seiten.
        if bis_kapitel is not None:
            unit, target = "chapters", bis_kapitel
        elif bis_seite is not None:
            unit, target = "pages", bis_seite
        else:
            pages_total = (progress or {}).get("total_override") or book.get("total_pages")
            prefers_chapters = bool(progress) and progress["mode"] == "chapters" and book.get("total_chapters")
            if prefers_chapters or (not pages_total and book.get("total_chapters")):
                unit, target = "chapters", book["total_chapters"]
            elif pages_total:
                unit, target = "pages", pages_total
            else:
                await reply(
                    "❌ Für dieses Buch kenne ich weder Seiten- noch Kapitelzahl. "
                    "Gib das Ziel direkt an, z.B. `bis_seite:300` oder `bis_kapitel:12`."
                )
                return

        current = progress_in_unit(progress, unit, book)
        if current is None:
            einheit = "Kapiteln" if unit == "chapters" else "Seiten"
            await reply(
                f"❌ Dein Stand lässt sich nicht in {einheit} ablesen. "
                f"Trag ihn einmal mit `/fortschritt` in {einheit} ein, dann klappt das Ziel."
            )
            return
        if current >= target:
            await reply(f"Du bist schon bei {current} {unit_label(unit, current)}. Dieses Ziel hast du erreicht. 🎉")
            return

        await self.bot.db.set_goal(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            isbn=book["isbn"],
            unit=unit,
            target=target,
            deadline=deadline.isoformat(),
            start_value=current,
            start_date=today.isoformat(),
        )
        goal = await self.bot.db.get_goal(interaction.user.id, interaction.guild_id, book["isbn"])
        pace = compute_pace(goal, current, today)
        reminder = await self.bot.db.get_reminder(interaction.user.id, interaction.guild_id, book["isbn"])
        hint = (
            "Deine Erinnerung bleibt eingeschaltet."
            if reminder
            else "Eine Erinnerung gibt es nur, wenn du sie mit `/erinnerung an` einschaltest."
        )
        await reply(f"🎯 Leseziel für *{book['title']}* gesetzt.\n{describe_pace(goal, pace)}\n{hint}")

    @leseziel.command(name="zeigen", description="Zeigt dein Leseziel und was es heute bedeutet.")
    async def zeigen(self, interaction: discord.Interaction) -> None:
        book = await self.bot.db.get_book()
        goal = book and await self.bot.db.get_goal(interaction.user.id, interaction.guild_id, book["isbn"])
        if not goal:
            await interaction.response.send_message(
                "Du hast kein Leseziel. Mit `/leseziel setzen` legst du eins an.", ephemeral=True
            )
            return

        progress = await self.bot.db.get_progress(interaction.user.id, interaction.guild_id, book["isbn"])
        current = progress_in_unit(progress, goal["unit"], book)
        if current is None:
            einheit = "Kapiteln" if goal["unit"] == "chapters" else "Seiten"
            await interaction.response.send_message(
                f"Dein Ziel zählt in {einheit}, dein letzter Stand nicht. "
                f"Trag ihn mit `/fortschritt` in {einheit} ein, dann rechne ich wieder.",
                ephemeral=True,
            )
            return

        today = datetime.now(club_timezone()).date()
        pace = compute_pace(goal, current, today)
        reminder = await self.bot.db.get_reminder(interaction.user.id, interaction.guild_id, book["isbn"])
        reminder_text = (
            f"Erinnerung: an, höchstens alle {reminder['interval_days']} Tage." if reminder else "Erinnerung: aus."
        )
        await interaction.response.send_message(
            f"🎯 *{book['title']}*\n{describe_pace(goal, pace)}\n{reminder_text}", ephemeral=True
        )

    @leseziel.command(name="loeschen", description="Entfernt dein Leseziel.")
    async def loeschen(self, interaction: discord.Interaction) -> None:
        book = await self.bot.db.get_book()
        removed = book and await self.bot.db.delete_goal(interaction.user.id, interaction.guild_id, book["isbn"])
        await interaction.response.send_message(
            "Leseziel entfernt, eine Erinnerung dazu auch." if removed else "Du hattest kein Leseziel.",
            ephemeral=True,
        )

    # ── /erinnerung ───────────────────────────────────────────────────────────

    @erinnerung.command(name="an", description="Schaltet eine private Erinnerung an dein Leseziel ein.")
    @app_commands.describe(alle_tage="Höchstens alle wie viele Tage (Standard: 7)")
    async def an(
        self,
        interaction: discord.Interaction,
        alle_tage: app_commands.Range[int, 1, 30] = 7,
    ) -> None:
        book = await self.bot.db.get_book()
        goal = book and await self.bot.db.get_goal(interaction.user.id, interaction.guild_id, book["isbn"])
        if not goal:
            await interaction.response.send_message(
                "Eine Erinnerung braucht ein Leseziel. Leg zuerst eins mit `/leseziel setzen` an.",
                ephemeral=True,
            )
            return

        await self.bot.db.enable_reminder(interaction.user.id, interaction.guild_id, book["isbn"], alle_tage)
        tage = "jeden Tag" if alle_tage == 1 else f"alle {alle_tage} Tage"
        await interaction.response.send_message(
            f"🔔 Erinnerung eingeschaltet: höchstens {tage}, als Direktnachricht, "
            "und nur wenn du hinter deinem Tempo liegst. Ausschalten mit `/erinnerung aus`.",
            ephemeral=True,
        )

    @erinnerung.command(name="aus", description="Schaltet deine Erinnerung aus.")
    async def aus(self, interaction: discord.Interaction) -> None:
        book = await self.bot.db.get_book()
        removed = book and await self.bot.db.disable_reminder(interaction.user.id, interaction.guild_id, book["isbn"])
        await interaction.response.send_message(
            "🔕 Erinnerung ausgeschaltet." if removed else "Du hattest keine Erinnerung eingeschaltet.",
            ephemeral=True,
        )

    # ── Versand ───────────────────────────────────────────────────────────────

    async def _send_dm(self, user_id: int, text: str) -> None:
        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        await user.send(text)

    @tasks.loop(hours=1)
    async def reminder_loop(self) -> None:
        local = datetime.now(club_timezone())
        if not QUIET_BEFORE_HOUR <= local.hour < QUIET_FROM_HOUR:
            return
        try:
            sent = await send_due_reminders(self.bot.db, self._send_dm, datetime.now(timezone.utc), local.date())
            if sent:
                log.info(f"{sent} Erinnerung(en) verschickt.")
        except Exception:
            log.exception("Erinnerungslauf fehlgeschlagen.")

    @reminder_loop.before_loop
    async def before_reminder_loop(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Goals(bot))
