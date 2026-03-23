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
    elif mode == "percent":
        bar = _progress_bar(current, 100)
        return f"`{bar}` {current}%"
    else:  # chapters
        total = book.get("total_chapters") if book else None
        sup_mode = p.get("supplement_mode")
        sup_val = p.get("supplement_value")

        chapter_str = f"Kapitel {current}/{total}" if total else f"Kapitel {current}"

        if sup_mode == "percent" and sup_val is not None:
            bar = _progress_bar(sup_val, 100)
            return f"`{bar}` {chapter_str} ({sup_val}%)"
        elif sup_mode == "pages" and sup_val is not None:
            page_total = p.get("total_override") or (book.get("total_pages") if book else None)
            if page_total:
                page_pct = min(round(sup_val / page_total * 100), 100)
                bar = _progress_bar(sup_val, page_total)
                return f"`{bar}` {chapter_str} · Seite {sup_val}/{page_total} ({page_pct}%)"
            bar = _progress_bar(current, total) if total else BAR_EMPTY * BAR_LENGTH
            return f"`{bar}` {chapter_str} · Seite {sup_val}"
        elif total:
            percent = min(round(current / total * 100), 100)
            bar = _progress_bar(current, total)
            return f"`{bar}` {chapter_str} ({percent}%)"
        return chapter_str


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
        prozent="Lesefortschritt in Prozent, z.B. vom Kindle (0–100). Auch kombinierbar mit kapitel:",
        seiten_gesamt="Deine persönliche Gesamtseitenzahl (für Ebook-Anpassung)",
    )
    async def fortschritt(
        self,
        interaction: discord.Interaction,
        seite: int | None = None,
        kapitel: int | None = None,
        prozent: app_commands.Range[int, 0, 100] | None = None,
        seiten_gesamt: int | None = None,
    ) -> None:
        """Lesefortschritt aktualisieren."""
        # kapitel darf mit seite ODER prozent kombiniert werden, aber nicht beides
        if kapitel is not None and seite is not None and prozent is not None:
            await interaction.response.send_message(
                "❌ Bitte nur `kapitel` + `seite` **oder** `kapitel` + `prozent` angeben, nicht alle drei.",
                ephemeral=True,
            )
            return

        # seite + prozent ohne kapitel ist nicht sinnvoll
        if kapitel is None and seite is not None and prozent is not None:
            await interaction.response.send_message(
                "❌ `seite` und `prozent` können nicht kombiniert werden.",
                ephemeral=True,
            )
            return

        # seite + kapitel ohne prozent war früher ungültig — jetzt ist kapitel primär, seite supplement
        # nichts angegeben
        if seite is None and kapitel is None and prozent is None:
            await interaction.response.send_message(
                "❌ Bitte einen Wert angeben: `seite`, `kapitel` oder `prozent`.\n"
                "Tipp: `/fortschritt kapitel:11 prozent:46` kombiniert Kapitel und Kindle-%",
                ephemeral=True,
            )
            return

        await interaction.response.defer()

        # Modus bestimmen
        if kapitel is not None:
            mode, current = "chapters", kapitel
            sup_mode = "percent" if prozent is not None else ("pages" if seite is not None else None)
            sup_val = prozent if prozent is not None else seite
        elif seite is not None:
            mode, current = "pages", seite
            sup_mode, sup_val = None, None
        else:
            mode, current = "percent", prozent
            sup_mode, sup_val = None, None

        await self.bot.db.update_progress(
            user_id=interaction.user.id,
            guild_id=interaction.guild_id,
            mode=mode,
            current=current,
            total_override=seiten_gesamt if mode == "pages" else None,
            supplement_mode=sup_mode,
            supplement_value=sup_val,
        )

        log.info(
            f"Fortschritt: {interaction.user} → {mode}={current}"
            + (f" +{sup_mode}={sup_val}" if sup_mode else "")
            + (f" (gesamt={seiten_gesamt})" if seiten_gesamt and mode == "pages" else "")
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
        name="buchketiere",
        description="Zeigt den Lesefortschritt aller Buchclub-Mitglieder."
    )
    async def buchketiere(self, interaction: discord.Interaction) -> None:
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

        embed.set_footer(text=f"{len(entries)} Buchketier(e) tracken ihren Fortschritt")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Progress(bot))
