"""
Tests für die Datenbankschicht (database.py)

Nutzt eine In-Memory SQLite-Datenbank — kein echtes .db File nötig.
Tests laufen vollständig ohne Discord-Verbindung.
"""

import pytest
from database import Database


@pytest.fixture
async def db():
    """Frische In-Memory-Datenbank für jeden Test."""
    database = Database(":memory:")
    await database.setup()
    return database


# ── Buch-Tests ────────────────────────────────────────────────────────────────

async def test_get_book_returns_none_when_empty(db):
    """Kein Buch → None zurückgeben."""
    result = await db.get_book()
    assert result is None


async def test_set_and_get_book(db):
    """Buch setzen und wieder abrufen."""
    await db.set_book(
        isbn="9783453319875",
        title="Der Schwarm",
        author="Frank Schätzing",
        description="Ein Thriller über das Meer.",
        cover_url="https://example.com/cover.jpg",
        total_pages=987,
        set_by=123456789,
    )
    book = await db.get_book()

    assert book is not None
    assert book["title"] == "Der Schwarm"
    assert book["author"] == "Frank Schätzing"
    assert book["total_pages"] == 987
    assert book["isbn"] == "9783453319875"


async def test_set_book_overwrites_previous(db):
    """Neues Buch setzen ersetzt das alte (immer nur 1 Buch)."""
    await db.set_book("111", "Buch Eins", None, None, None, 100, 1)
    await db.set_book("222", "Buch Zwei", None, None, None, 200, 1)

    book = await db.get_book()
    assert book["title"] == "Buch Zwei"
    assert book["isbn"] == "222"


async def test_set_chapter(db):
    """Kapitelanzahl für aktuelles Buch setzen."""
    await db.set_book("111", "Test", None, None, None, None, 1)
    ok = await db.set_chapter(24)

    assert ok is True
    book = await db.get_book()
    assert book["total_chapters"] == 24


async def test_set_chapter_without_book_returns_false(db):
    """set_chapter ohne aktives Buch gibt False zurück."""
    ok = await db.set_chapter(24)
    assert ok is False


# ── Fortschritts-Tests ────────────────────────────────────────────────────────

async def test_get_progress_returns_none_when_empty(db):
    """Kein Fortschritt → None zurückgeben."""
    result = await db.get_progress(user_id=1, guild_id=1)
    assert result is None


async def test_update_and_get_progress_pages(db):
    """Seitenfortschritt setzen und abrufen."""
    await db.update_progress(
        user_id=111, guild_id=999, mode="pages", current=142
    )
    p = await db.get_progress(user_id=111, guild_id=999)

    assert p is not None
    assert p["mode"] == "pages"
    assert p["current"] == 142
    assert p["total_override"] is None


async def test_update_progress_with_total_override(db):
    """User-spezifische Gesamtseitenzahl (Ebook-Anpassung)."""
    await db.update_progress(
        user_id=111, guild_id=999, mode="pages", current=50, total_override=320
    )
    p = await db.get_progress(user_id=111, guild_id=999)

    assert p["total_override"] == 320


async def test_update_progress_keeps_override_on_update(db):
    """total_override bleibt erhalten wenn nicht neu angegeben."""
    await db.update_progress(111, 999, "pages", 50, total_override=320)
    await db.update_progress(111, 999, "pages", 100)  # kein override

    p = await db.get_progress(111, 999)
    assert p["total_override"] == 320  # wurde behalten
    assert p["current"] == 100


async def test_update_progress_chapters(db):
    """Kapitel-Fortschritt setzen."""
    await db.update_progress(user_id=222, guild_id=999, mode="chapters", current=5)
    p = await db.get_progress(user_id=222, guild_id=999)

    assert p["mode"] == "chapters"
    assert p["current"] == 5


async def test_get_all_progress_empty(db):
    """Keine Einträge → leere Liste."""
    result = await db.get_all_progress(guild_id=999)
    assert result == []


async def test_get_all_progress_multiple_users(db):
    """Mehrere User → alle zurückgeben."""
    await db.update_progress(111, 999, "pages", 200)
    await db.update_progress(222, 999, "pages", 50)
    await db.update_progress(333, 999, "chapters", 8)

    entries = await db.get_all_progress(guild_id=999)
    assert len(entries) == 3


async def test_get_all_progress_only_same_guild(db):
    """Nur Einträge des gleichen Servers zurückgeben."""
    await db.update_progress(111, guild_id=999, mode="pages", current=100)
    await db.update_progress(111, guild_id=888, mode="pages", current=50)  # anderer Server

    entries = await db.get_all_progress(guild_id=999)
    assert len(entries) == 1
    assert entries[0]["current"] == 100
