"""
Cog: Bücher

Slash Commands für das Verwalten und Anzeigen des aktuellen Buchclub-Buches.

Commands:
    /buch         — Aktuelles Buch mit Klappentext anzeigen
    /buch-setzen  — Neues Buch via ISBN setzen (Admin)
    /set-chapter  — Kapitel setzen (Admin)
"""

import os
import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.openlibrary import fetch_book_by_isbn

log = logging.getLogger("buchclub.books")


def has_admin_role():
    """Check: User hat die konfigurierte Admin-Rolle."""
    async def predicate(interaction: discord.Interaction) -> bool:
        role_name = os.getenv("ADMIN_ROLE_NAME", "Buchclub-Admin")
        user_roles = [r.name for r in interaction.user.roles]
        if role_name not in user_roles:
            await interaction.response.send_message(
                f"❌ Du brauchst die Rolle **{role_name}** für diesen Command.",
                ephemeral=True,
            )
            return False
        return True
    return app_commands.check(predicate)


class Books(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="buch", description="Zeigt das aktuelle Buchclub-Buch mit Klappentext.")
    async def buch(self, interaction: discord.Interaction) -> None:
        """Aktuelles Buch anzeigen."""
        await interaction.response.defer()

        book = await self.bot.db.get_book()
        if not book:
            await interaction.followup.send(
                "📭 Noch kein Buch gesetzt. Ein Admin kann mit `/buch-setzen` ein Buch festlegen."
            )
            return

        embed = _build_book_embed(book)
        await interaction.followup.send(embed=embed)

    @app_commands.command(
        name="buch-setzen",
        description="[Admin] Setzt das aktuelle Buch via ISBN."
    )
    @app_commands.describe(isbn="ISBN-10 oder ISBN-13 des Buches")
    @has_admin_role()
    async def buch_setzen(self, interaction: discord.Interaction, isbn: str) -> None:
        """Neues Buch via ISBN setzen (nur für Admins)."""
        await interaction.response.defer(thinking=True)

        book_data = await fetch_book_by_isbn(isbn)
        if not book_data:
            await interaction.followup.send(
                f"❌ Kein Buch mit ISBN **{isbn}** gefunden. "
                "Bitte ISBN prüfen (ohne Bindestriche oder mit — beides klappt)."
            )
            return

        await self.bot.db.set_book(
            isbn=book_data["isbn"],
            title=book_data["title"],
            author=book_data["author"],
            description=book_data["description"],
            cover_url=book_data["cover_url"],
            total_pages=book_data["total_pages"],
            set_by=interaction.user.id,
        )

        log.info(f"Buch gesetzt: '{book_data['title']}' (ISBN: {isbn}) von {interaction.user}")

        embed = _build_book_embed(book_data)
        embed.set_footer(text=f"Gesetzt von {interaction.user.display_name}")
        await interaction.followup.send(
            content="✅ **Neues Buchclub-Buch gesetzt!**",
            embed=embed,
        )
    
    @app_commands.command(
        name="set-chapter",
        description="[Admin] Setzt die Anzahl der Kapitel."
    )
    @app_commands.describe(chapter="Anzahl der Kapitel")
    @has_admin_role()
    async def set_chapter(self, interaction: discord.Interaction, chapter: int) -> None:
        """Setzt die Anzahl der Kapitel (nur für Admins)."""
        await interaction.response.defer(thinking=True)

        ok = await self.bot.db.set_chapter(chapter)
        if not ok:
            await interaction.followup.send(
                "❌ Noch kein Buch gesetzt. Zuerst `/buch-setzen` verwenden.",
                ephemeral=True,
            )
            return

        log.info(f"Kapitel gesetzt: {chapter} von {interaction.user}")

        book = await self.bot.db.get_book()
        await interaction.followup.send(
            content=f"✅ **{book['title']}** hat **{chapter} Kapitel**.",
        )


def _build_book_embed(book: dict) -> discord.Embed:
    """Discord Embed für ein Buch erstellen."""
    embed = discord.Embed(
        title=book["title"],
        color=discord.Color.from_rgb(139, 90, 43),  # Buchrücken-Braun
    )

    if book.get("author"):
        embed.set_author(name=f"von {book['author']}")

    if book.get("description"):
        # Discord Embeds: max 4096 Zeichen für description
        desc = book["description"]
        if len(desc) > 1024:
            desc = desc[:1021] + "..."
        embed.add_field(name="📖 Klappentext", value=desc, inline=False)

    if book.get("total_pages"):
        embed.add_field(name="📄 Seiten", value=str(book["total_pages"]), inline=True)

    if book.get("isbn"):
        embed.add_field(name="ISBN", value=book["isbn"], inline=True)

    if book.get("cover_url"):
        embed.set_thumbnail(url=book["cover_url"])

    return embed


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Books(bot))
