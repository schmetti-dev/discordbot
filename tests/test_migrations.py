"""
Tests für Migrationen und Sicherung

Eine Datenbank aus einer älteren Version muss ohne Verlust auf den aktuellen
Stand kommen, und eine Sicherung muss sich wieder öffnen lassen.
"""

import sqlite3
from datetime import datetime, timezone

import aiosqlite
import pytest

from database import Database
from migrations import MIGRATIONS, migrate
from services.backup import prune, run_backup, verify

ISBN = "9783453319875"

# Schema der ersten Version: kein Prozent-Modus, keine Zusatzangaben, keine ISBN am Fortschritt.
FIRST_RELEASE = """
    CREATE TABLE current_book (
        id INTEGER PRIMARY KEY CHECK (id = 1), isbn TEXT NOT NULL, title TEXT NOT NULL,
        author TEXT, description TEXT, cover_url TEXT, total_pages INTEGER,
        total_chapters INTEGER, set_by INTEGER, set_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE reading_progress (
        user_id INTEGER NOT NULL, guild_id INTEGER NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('pages', 'chapters')),
        current INTEGER NOT NULL DEFAULT 0, total_override INTEGER,
        updated_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (user_id, guild_id)
    );
"""


async def seed_first_release(path):
    async with aiosqlite.connect(path) as conn:
        await conn.executescript(FIRST_RELEASE)
        await conn.execute("INSERT INTO current_book (id, isbn, title, total_pages) VALUES (1, ?, 'Der Schwarm', 987)", (ISBN,))
        await conn.executemany(
            "INSERT INTO reading_progress (user_id, guild_id, mode, current, total_override, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            [(1, 999, "pages", 142, None, "2026-03-10 18:00:00"), (2, 999, "chapters", 5, None, "2026-03-11 09:30:00"), (3, 999, "pages", 50, 320, "2026-03-12 21:15:00")],
        )
        await conn.commit()


async def test_fresh_database_gets_every_migration(tmp_path):
    db = Database(str(tmp_path / "fresh.db"))
    await db.setup()
    async with db._conn.execute("SELECT version FROM schema_version ORDER BY version") as cursor:
        assert [row[0] for row in await cursor.fetchall()] == [version for version, _, _ in MIGRATIONS]
    await db.close()


async def test_first_release_database_upgrades_without_losing_a_row(tmp_path):
    path = str(tmp_path / "old.db")
    await seed_first_release(path)

    db = Database(path)
    await db.setup()

    rows = await db.get_all_progress(guild_id=999, isbn=ISBN)
    found = sorted((r["user_id"], r["mode"], r["current"], r["total_override"], r["updated_at"]) for r in rows)
    assert found == [
        (1, "pages", 142, None, "2026-03-10 18:00:00"),
        (2, "chapters", 5, None, "2026-03-11 09:30:00"),
        (3, "pages", 50, 320, "2026-03-12 21:15:00"),
    ]
    assert (await db.get_book())["title"] == "Der Schwarm"

    # Der Prozent-Modus und die neuen Tabellen sind da.
    await db.update_progress(4, 999, ISBN, "percent", 46)
    await db.set_goal(1, 999, ISBN, "pages", 987, "2026-10-31", 142, "2026-10-01")
    await db.close()


async def test_migrations_run_once(tmp_path):
    path = str(tmp_path / "twice.db")
    db = Database(path)
    await db.setup()
    await db.update_progress(1, 999, ISBN, "pages", 10)
    await db.close()

    async with aiosqlite.connect(path) as conn:
        assert await migrate(conn) == []
        async with conn.execute("SELECT COUNT(*) FROM reading_progress") as cursor:
            assert (await cursor.fetchone())[0] == 1


async def test_database_from_last_release_keeps_its_isbn_history(tmp_path):
    # v1.1.0 hatte schon das volle Grundschema, aber keine Versionstabelle.
    path = str(tmp_path / "v110.db")
    first = Database(path)
    await first.setup()
    await first.update_progress(1, 999, "1111111111", "pages", 300)
    await first.update_progress(1, 999, ISBN, "pages", 42)
    await first._conn.executescript("DROP TABLE schema_version; DROP TABLE reading_reminders; DROP TABLE reading_goals;")
    await first.close()

    db = Database(path)
    await db.setup()
    assert (await db.get_progress(1, 999, "1111111111"))["current"] == 300
    assert (await db.get_progress(1, 999, ISBN))["current"] == 42
    await db.close()


# ── Sicherung ─────────────────────────────────────────────────────────────────

async def test_backup_is_a_whole_readable_copy(tmp_path, monkeypatch):
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backup"))
    db = Database(str(tmp_path / "live.db"))
    await db.setup()
    await db.set_book(ISBN, "Der Schwarm", None, None, None, 987, 1)
    await db.update_progress(1, 999, ISBN, "pages", 142)

    copy = await run_backup(db, datetime(2026, 10, 1, 3, 0, tzinfo=timezone.utc))
    await db.close()

    assert copy.name == "buchclub-2026-10-01T03-00-00Z.db"
    assert verify(copy) is True

    # Wiederherstellen heißt: die Kopie als Datenbank öffnen und alles ist da.
    restored = Database(str(copy))
    await restored.setup()
    assert (await restored.get_book())["title"] == "Der Schwarm"
    assert (await restored.get_progress(1, 999, ISBN))["current"] == 142
    await restored.close()


async def test_no_backup_without_target(tmp_path, monkeypatch):
    monkeypatch.delenv("BACKUP_DIR", raising=False)
    db = Database(":memory:")
    await db.setup()
    assert await run_backup(db) is None
    await db.close()


def test_prune_keeps_the_newest(tmp_path):
    for day in range(1, 6):
        (tmp_path / f"buchclub-2026-10-0{day}T03-00-00Z.db").write_bytes(b"x")
    (tmp_path / "etwas-anderes.txt").write_text("bleibt")

    removed = prune(tmp_path, keep=2)

    assert sorted(p.name for p in removed) == [f"buchclub-2026-10-0{day}T03-00-00Z.db" for day in (1, 2, 3)]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "buchclub-2026-10-04T03-00-00Z.db",
        "buchclub-2026-10-05T03-00-00Z.db",
        "etwas-anderes.txt",
    ]


def test_verify_rejects_a_broken_file(tmp_path):
    broken = tmp_path / "buchclub-kaputt.db"
    broken.write_bytes(b"das ist keine Datenbank" * 100)
    with pytest.raises(sqlite3.DatabaseError):
        verify(broken)
