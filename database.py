"""
Datenbankschicht — SQLite via aiosqlite

Verwaltet das Schema und alle Datenbankoperationen für:
- Bücher (aktuelles Buch + Metadaten)
- Lesefortschritt pro User
- User-Stats (Aktivitätszähler)

Design: Eine persistente Verbindung (geöffnet in setup(), geschlossen beim Bot-Shutdown).
Das ermöglicht sauberes Testen mit :memory: Datenbanken.
"""

import aiosqlite


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def setup(self) -> None:
        """Verbindung öffnen und Schema erstellen falls nicht vorhanden."""
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript("""
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

            -- Lesefortschritt pro User + Buch (isbn als Teil des PK für History)
            CREATE TABLE IF NOT EXISTS reading_progress (
                user_id          INTEGER NOT NULL,
                guild_id         INTEGER NOT NULL,
                isbn             TEXT    NOT NULL DEFAULT '',
                mode             TEXT    NOT NULL CHECK (mode IN ('pages', 'chapters', 'percent')),
                current          INTEGER NOT NULL DEFAULT 0,
                total_override   INTEGER,
                supplement_mode  TEXT CHECK (supplement_mode IN ('pages', 'percent') OR supplement_mode IS NULL),
                supplement_value INTEGER,
                updated_at       TEXT DEFAULT (datetime('now')),
                PRIMARY KEY (user_id, guild_id, isbn)
            );

            -- User-Statistiken (Aktivitätszähler)
            CREATE TABLE IF NOT EXISTS user_stats (
                user_id           INTEGER NOT NULL,
                guild_id          INTEGER NOT NULL,
                fortschritt_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, guild_id)
            );
        """)
        await self._conn.commit()

        # Migration: add 'percent' mode + supplement columns to existing databases
        async with self._conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='reading_progress'"
        ) as cursor:
            row = await cursor.fetchone()
            if row and ("'percent'" not in row[0] or "supplement_mode" not in row[0]):
                await self._conn.executescript("""
                    CREATE TABLE reading_progress_new (
                        user_id          INTEGER NOT NULL,
                        guild_id         INTEGER NOT NULL,
                        isbn             TEXT    NOT NULL DEFAULT '',
                        mode             TEXT NOT NULL CHECK (mode IN ('pages', 'chapters', 'percent')),
                        current          INTEGER NOT NULL DEFAULT 0,
                        total_override   INTEGER,
                        supplement_mode  TEXT CHECK (supplement_mode IN ('pages', 'percent') OR supplement_mode IS NULL),
                        supplement_value INTEGER,
                        updated_at       TEXT DEFAULT (datetime('now')),
                        PRIMARY KEY (user_id, guild_id, isbn)
                    );
                    INSERT INTO reading_progress_new (user_id, guild_id, mode, current, total_override, updated_at)
                        SELECT user_id, guild_id, mode, current, total_override, updated_at FROM reading_progress;
                    DROP TABLE reading_progress;
                    ALTER TABLE reading_progress_new RENAME TO reading_progress;
                """)
                await self._conn.commit()

        # Migration: add isbn column if missing (existing DBs without it)
        async with self._conn.execute(
            "PRAGMA table_info(reading_progress)"
        ) as cursor:
            cols = [row[1] for row in await cursor.fetchall()]
        if "isbn" not in cols:
            await self._conn.execute(
                "ALTER TABLE reading_progress ADD COLUMN isbn TEXT NOT NULL DEFAULT ''"
            )
            await self._conn.execute("""
                UPDATE reading_progress
                SET isbn = COALESCE((SELECT isbn FROM current_book WHERE id = 1), '')
                WHERE isbn = ''
            """)
            await self._conn.commit()

    async def close(self) -> None:
        """Verbindung sauber schließen."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    # ── Buch-Operationen ──────────────────────────────────────────────────────

    async def set_book(self, isbn: str, title: str, author: str | None,
                       description: str | None, cover_url: str | None,
                       total_pages: int | None, set_by: int) -> None:
        """Aktuelles Buch setzen (ersetzt vorherigen Eintrag)."""
        await self._conn.execute("""
            INSERT INTO current_book (id, isbn, title, author, description, cover_url, total_pages, set_by, set_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                isbn=excluded.isbn, title=excluded.title, author=excluded.author,
                description=excluded.description, cover_url=excluded.cover_url,
                total_pages=excluded.total_pages, set_by=excluded.set_by,
                set_at=excluded.set_at, total_chapters=NULL
        """, (isbn, title, author, description, cover_url, total_pages, set_by))
        await self._conn.commit()

    async def get_book(self) -> dict | None:
        """Aktuelles Buch abrufen oder None wenn keins gesetzt."""
        async with self._conn.execute("SELECT * FROM current_book WHERE id = 1") as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def set_total_chapters(self, total: int) -> bool:
        """
        Kapitelanzahl für aktuelles Buch setzen.

        Returns:
            True wenn erfolgreich gesetzt, False wenn kein Buch aktiv ist.
        """
        cursor = await self._conn.execute(
            "UPDATE current_book SET total_chapters = ? WHERE id = 1", (total,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # ── Fortschritts-Operationen ──────────────────────────────────────────────

    async def update_progress(self, user_id: int, guild_id: int, isbn: str,
                               mode: str, current: int,
                               total_override: int | None = None,
                               supplement_mode: str | None = None,
                               supplement_value: int | None = None) -> None:
        """Lesefortschritt eines Users für ein bestimmtes Buch setzen oder aktualisieren."""
        await self._conn.execute("""
            INSERT INTO reading_progress
                (user_id, guild_id, isbn, mode, current, total_override, supplement_mode, supplement_value, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(user_id, guild_id, isbn) DO UPDATE SET
                mode=excluded.mode, current=excluded.current,
                total_override=COALESCE(excluded.total_override, total_override),
                supplement_mode=excluded.supplement_mode,
                supplement_value=excluded.supplement_value,
                updated_at=excluded.updated_at
        """, (user_id, guild_id, isbn, mode, current, total_override, supplement_mode, supplement_value))
        await self._conn.commit()

    async def get_progress(self, user_id: int, guild_id: int, isbn: str) -> dict | None:
        """Fortschritt eines Users für ein bestimmtes Buch abrufen."""
        async with self._conn.execute("""
            SELECT * FROM reading_progress
            WHERE user_id = ? AND guild_id = ? AND isbn = ?
        """, (user_id, guild_id, isbn)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_all_progress(self, guild_id: int, isbn: str) -> list[dict]:
        """Alle Fortschritte eines Servers für ein bestimmtes Buch, sortiert nach Fortschritt."""
        async with self._conn.execute("""
            SELECT * FROM reading_progress
            WHERE guild_id = ? AND isbn = ?
            ORDER BY mode, current DESC
        """, (guild_id, isbn)) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]

    # ── User-Stats-Operationen ────────────────────────────────────────────────

    async def increment_fortschritt_count(self, user_id: int, guild_id: int) -> None:
        """Fortschritt-Nutzungszähler für einen User erhöhen."""
        await self._conn.execute(
            "INSERT OR IGNORE INTO user_stats (user_id, guild_id) VALUES (?, ?)",
            (user_id, guild_id)
        )
        await self._conn.execute(
            "UPDATE user_stats SET fortschritt_count = fortschritt_count + 1 WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        )
        await self._conn.commit()

    async def get_user_profile(self, user_id: int, guild_id: int) -> dict:
        """Profildaten eines Users aggregieren."""
        book = await self.get_book()
        current_isbn = book["isbn"] if book else None

        # fortschritt_count
        async with self._conn.execute(
            "SELECT fortschritt_count FROM user_stats WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id)
        ) as cursor:
            stats_row = await cursor.fetchone()
        fortschritt_count = stats_row["fortschritt_count"] if stats_row else 0

        # books completed = distinct isbns mit Fortschritt, außer aktuellem Buch
        async with self._conn.execute("""
            SELECT COUNT(DISTINCT isbn) as cnt FROM reading_progress
            WHERE user_id = ? AND guild_id = ? AND isbn != ? AND isbn != ''
        """, (user_id, guild_id, current_isbn or "")) as cursor:
            cnt_row = await cursor.fetchone()
        books_completed = cnt_row["cnt"] if cnt_row else 0

        # letztes Buch (nicht das aktuelle)
        async with self._conn.execute("""
            SELECT isbn, updated_at FROM reading_progress
            WHERE user_id = ? AND guild_id = ? AND isbn != ? AND isbn != ''
            ORDER BY updated_at DESC LIMIT 1
        """, (user_id, guild_id, current_isbn or "")) as cursor:
            last_row = await cursor.fetchone()
        last_isbn = last_row["isbn"] if last_row else None
        last_updated_at = last_row["updated_at"] if last_row else None

        # aktueller Fortschritt
        current_progress = None
        if current_isbn:
            current_progress = await self.get_progress(user_id, guild_id, current_isbn)

        return {
            "fortschritt_count": fortschritt_count,
            "books_completed": books_completed,
            "last_isbn": last_isbn,
            "last_updated_at": last_updated_at,
            "progress": current_progress,
            "current_book": book,
        }
