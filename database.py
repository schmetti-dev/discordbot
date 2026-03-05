"""
Datenbankschicht — SQLite via aiosqlite

Verwaltet das Schema und alle Datenbankoperationen für:
- Bücher (aktuelles Buch + Metadaten)
- Lesefortschritt pro User
"""

import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path

    async def setup(self) -> None:
        """Schema erstellen falls nicht vorhanden."""
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                -- Aktuelles Buch (immer max. 1 Eintrag)
                CREATE TABLE IF NOT EXISTS current_book (
                    id          INTEGER PRIMARY KEY CHECK (id = 1),
                    isbn        TEXT NOT NULL,
                    title       TEXT NOT NULL,
                    author      TEXT,
                    description TEXT,
                    cover_url   TEXT,
                    total_pages INTEGER,       -- Aus API, anpassbar
                    total_chapters INTEGER,    -- Optional, manuell gesetzt
                    set_by      INTEGER,       -- Discord User ID des Admins
                    set_at      TEXT DEFAULT (datetime('now'))
                );

                -- Lesefortschritt pro User
                CREATE TABLE IF NOT EXISTS reading_progress (
                    user_id         INTEGER NOT NULL,
                    guild_id        INTEGER NOT NULL,
                    mode            TEXT NOT NULL CHECK (mode IN ('pages', 'chapters')),
                    current         INTEGER NOT NULL DEFAULT 0,
                    total_override  INTEGER,   -- User-spezifische Gesamtseitenzahl (Ebook-Anpassung)
                    updated_at      TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, guild_id)
                );
            """)
            await db.commit()

    # ── Buch-Operationen ──────────────────────────────────────────────────────

    async def set_book(self, isbn: str, title: str, author: str | None,
                       description: str | None, cover_url: str | None,
                       total_pages: int | None, set_by: int) -> None:
        """Aktuelles Buch setzen (ersetzt vorherigen Eintrag)."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO current_book (id, isbn, title, author, description, cover_url, total_pages, set_by, set_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    isbn=excluded.isbn, title=excluded.title, author=excluded.author,
                    description=excluded.description, cover_url=excluded.cover_url,
                    total_pages=excluded.total_pages, set_by=excluded.set_by,
                    set_at=excluded.set_at, total_chapters=NULL
            """, (isbn, title, author, description, cover_url, total_pages, set_by))
            await db.commit()

    async def get_book(self) -> dict | None:
        """Aktuelles Buch abrufen oder None wenn keins gesetzt."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM current_book WHERE id = 1") as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def set_total_chapters(self, total: int) -> None:
        """Kapitelanzahl für aktuelles Buch setzen."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE current_book SET total_chapters = ? WHERE id = 1", (total,)
            )
            await db.commit()

    # ── Fortschritts-Operationen ──────────────────────────────────────────────

    async def update_progress(self, user_id: int, guild_id: int,
                               mode: str, current: int,
                               total_override: int | None = None) -> None:
        """Lesefortschritt eines Users setzen oder aktualisieren."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("""
                INSERT INTO reading_progress (user_id, guild_id, mode, current, total_override, updated_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(user_id, guild_id) DO UPDATE SET
                    mode=excluded.mode, current=excluded.current,
                    total_override=COALESCE(excluded.total_override, total_override),
                    updated_at=excluded.updated_at
            """, (user_id, guild_id, mode, current, total_override))
            await db.commit()

    async def get_progress(self, user_id: int, guild_id: int) -> dict | None:
        """Fortschritt eines einzelnen Users abrufen."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM reading_progress
                WHERE user_id = ? AND guild_id = ?
            """, (user_id, guild_id)) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def get_all_progress(self, guild_id: int) -> list[dict]:
        """Alle Fortschritte eines Servers, sortiert nach Fortschritt."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("""
                SELECT * FROM reading_progress
                WHERE guild_id = ?
                ORDER BY mode, current DESC
            """, (guild_id,)) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]
