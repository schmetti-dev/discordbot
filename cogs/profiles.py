"""
Cog: Buchketier-Profile

Slash Command für das Anzeigen von User-Leserprofilen.

Commands:
    /buchketier — Leserprofil eines Mitglieds anzeigen
"""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from services.openlibrary import fetch_book_by_isbn
from cogs.progress import _format_progress

log = logging.getLogger("buchclub.profiles")

# Level-System: (min_bücher, titel, embed_farbe)
LEVEL_TIERS = [
    (0,  "Bücherwurm",             0x8B4513),
    (3,  "Leseraupe",              0x6A8759),
    (7,  "Seitenflüsterer",        0x4A90D9),
    (12, "Büchernarr",             0xD4A017),
    (20, "Lesemeister",            0xC0392B),
    (30, "Bibliophiler",           0x8E44AD),
    (50, "Großmeister der Seiten", 0x2C3E50),
]


def _get_level(books_completed: int) -> tuple[str, int]:
    """Gibt (titel, farbe) für die Anzahl abgeschlossener Bücher zurück."""
    title, color = LEVEL_TIERS[0][1], LEVEL_TIERS[0][2]
    for threshold, t, c in LEVEL_TIERS:
        if books_completed >= threshold:
            title, color = t, c
    return title, color


def _get_next_level(books_completed: int) -> tuple[str, int] | None:
    """Gibt (nächster_titel, bücher_noch_nötig) zurück, oder None wenn max Level."""
    for threshold, title, _ in LEVEL_TIERS:
        if books_completed < threshold:
            return title, threshold - books_completed
    return None


class Profiles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="buchketier",
        description="Zeigt das Leserprofil eines Mitglieds an."
    )
    @app_commands.describe(mitglied="Das Mitglied, dessen Profil du sehen möchtest.")
    async def buchketier(
        self,
        interaction: discord.Interaction,
        mitglied: discord.Member | None = None,
    ) -> None:
        """Leserprofil anzeigen."""
        await interaction.response.defer()

        target = mitglied or interaction.user
        profile = await self.bot.db.get_user_profile(target.id, interaction.guild_id)

        books_completed = profile["books_completed"]
        level_title, level_color = _get_level(books_completed)
        next_level = _get_next_level(books_completed)

        embed = discord.Embed(
            title=f"📚 {target.display_name}",
            color=level_color,
        )
        embed.set_thumbnail(url=target.display_avatar.url)

        # Rang
        level_text = f"**{level_title}**"
        if next_level:
            next_title, books_needed = next_level
            buch_pl = "Buch" if books_needed == 1 else "Bücher"
            level_text += f"\n_{books_needed} {buch_pl} bis „{next_title}"_"
        embed.add_field(name="Rang", value=level_text, inline=True)

        # Bücher abgeschlossen
        embed.add_field(name="Bücher abgeschlossen", value=str(books_completed), inline=True)

        # Aktivität
        embed.add_field(
            name="Aktivität",
            value=f"{profile['fortschritt_count']}× /fortschritt",
            inline=True,
        )

        # Zuletzt gelesen
        if profile["last_isbn"]:
            last_title = profile["last_isbn"]  # Fallback: ISBN
            try:
                book_data = await fetch_book_by_isbn(profile["last_isbn"])
                if book_data:
                    last_title = book_data["title"]
                    if book_data.get("author"):
                        last_title += f" – {book_data['author']}"
            except Exception:
                log.warning(f"OpenLibrary-Lookup fehlgeschlagen für ISBN {profile['last_isbn']}")

            date_str = profile["last_updated_at"][:10] if profile["last_updated_at"] else ""
            embed.add_field(
                name="Zuletzt gelesen",
                value=f"_{last_title}_\n({date_str})" if date_str else f"_{last_title}_",
                inline=False,
            )
        else:
            embed.add_field(
                name="Zuletzt gelesen",
                value="_Noch kein Buch abgeschlossen._",
                inline=False,
            )

        # Aktueller Fortschritt
        if profile["progress"] and profile["current_book"]:
            progress_str = _format_progress(profile["progress"], profile["current_book"])
            embed.add_field(
                name=f"Aktuell: _{profile['current_book']['title']}_",
                value=progress_str,
                inline=False,
            )

        embed.set_footer(text="Buchclub · Viel Spaß beim Lesen! 📖")
        await interaction.followup.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Profiles(bot))
