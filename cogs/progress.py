"""
Cog: Lesefortschritt

Slash Commands für das Tracken und Anzeigen des Lesefortschritts.

Commands:
    /fortschritt  — Eigenen Fortschritt aktualisieren (Seiten oder Kapitel)
    /alle-fortschritte — Übersicht aller Mitglieder
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("buchclub.progress")

# Fortschrittsbalken: 10 Blöcke
BAR_LENGTH = 10
BAR_FILLED = "█"
BAR_EMPTY = "░"


def _progress_bar(current: int, total: int) -> str:
    """Gibt einen Unicode-Fortschrittsbalken zurück."""
    if total <= 0:
        return BAR_EMPTY * BAR_LENGTH
    ratio = min(current / total, 1.0)
    filled = round(ratio * BAR_LENGTH)
    return BAR_FILLED * filled + BAR_EMPTY * (BAR_LENGTH - filled)


def _format_progress(p: dict, book: dict | None) -> str:
    """Fortschrittseintrag als Textzeile formatieren."""
    mode = p["mode"]
    current = p["current"]

    if mode == "pages":
        total = p.get("total_override") or (book.get("total_pages") if book else None)
        if total:
            percent = min(round(current / total * 100), 100)
            bar = _progress_bar(current, total)
            return f"`{bar}` {current}/{total} Seiten ({percent}%)"
        return f"Seite {current}"
    else:  # chapters
        total = book.get("total_chapters") if book else None
        if total:
            percent = min(round(current / total * 100), 100)
            bar = _progress_bar(current, total)
            return f"`{bar}` Kapitel {current}/{total} ({percent}%)"
        return f"Kapitel {current}"


class Progress(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="fortschritt",
        description="Aktualisiere deinen Lesefortschritt."
    )
    @app_commands.describe(
        seite="Aktuelle Seite (z.B. 142)",
        kapitel="Aktuelles Kapitel (z.B. 5)",
        seiten_gesamt="Deine persönliche Gesamtseitenzahl (für Ebook-Anpassung)",
    )
    async def fortschritt(
        self,
        interaction: discord.Interaction,
        seite: int | None = None,
        kapitel: int | None = None,
        seiten_gesamt: int | None = None,
    ) -> None:
        """Lesefortschritt aktualisieren."""
        if seite is None and kapitel is None:
            await interaction.response.send_message(
                "❌ Bitte entweder `seite` oder `kapitel` angeben.\n"
                "Beispiel: `/fortschritt seite:142` oder `/fortschritt kapitel:5`",
                ephemeral=True,
            )
            return

        if seite is not None and kapitel is not None:
            await interaction.response.send_message(
                "❌ Bitte nur `seite` **oder** `kapitel` angeben, nicht beides.",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        mode = "pages" if seite is not None else "chapters"
        current = seite if seite is not None else kapitel

        if current < 0:
            await interaction.followup.send("❌ Der Wert kann nicht negativ sein.", ephemeral=True)
            return

        await self.bot.db.update_progress(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            mode=mode,
            current=current,
            total_override=seiten_gesamt,
        )

        log.info(
            f"Fortschritt: {interaction.user} → {mode}={current}"
            + (f" (gesamt={seiten_gesamt})" if seiten_gesamt else "")
        )

        book = await self.bot.db.get_book()
        p = await self.bot.db.get_progress(interaction.user.id, interaction.guild_id)

        progress_str = _format_progress(p, book)
        book_title = f"in *{book['title']}*" if book else ""

        embed = discord.Embed(
            description=f"**{interaction.user.display_name}** liest {book_title}\n{progress_str}",
            color=discord.Color.green(),
        )
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="alle-fortschritte",
        description="Zeigt den Lesefortschritt aller Buchclub-Mitglieder."
    )
    async def alle_fortschritte(self, interaction: discord.Interaction) -> None:
        """Fortschrittsübersicht aller User anzeigen."""
        await interaction.response.defer()

        book = await self.bot.db.get_book()
        entries = await self.bot.db.get_all_progress(interaction.guild_id)

        if not entries:
            await interaction.followup.send(
                "📭 Noch keine Fortschritte eingetragen. "
                "Nutze `/fortschritt` um deinen Stand zu setzen!"
            )
            return

        embed = discord.Embed(
            title="📚 Lesefortschritt",
            description=f"**{book['title']}**" if book else "",
            color=discord.Color.blurple(),
        )

        if book and book.get("cover_url"):
            embed.set_thumbnail(url=book["cover_url"])

        for entry in entries:
            member = interaction.guild.get_member(entry["user_id"])
            name = member.display_name if member else f"User {entry['user_id']}"
            progress_str = _format_progress(entry, book)
            embed.add_field(name=name, value=progress_str, inline=False)

        embed.set_footer(text=f"{len(entries)} Mitglied(er) tracken ihren Fortschritt")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Progress(bot))
