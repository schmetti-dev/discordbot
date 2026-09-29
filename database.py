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

from migrations import migrate
from services.goals import progress_in_unit


class Database:
    def __init__(self, path: str):
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    async def setup(self) -> None:
        """Verbindung öffnen und Schema auf den aktuellen Stand bringen."""
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA foreign_keys = ON")
        try:
            await migrate(self._conn)
        except Exception:
            # Eine offene Verbindung hält einen Thread am Leben: der Prozess würde
            # hängen statt abzustürzen, und kein Neustart des Containers griffe.
            await self.close()
            raise

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
        # Die Bücherliste merkt sich jedes Clubbuch, der Thread bleibt beim Überschreiben stehen.
        await self._conn.execute("""
            INSERT INTO books (isbn, title, total_pages, set_at) VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(isbn) DO UPDATE SET title=excluded.title, total_pages=excluded.total_pages
        """, (isbn, title, total_pages))
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
        await self._conn.execute(
            "UPDATE books SET total_chapters = ? WHERE isbn = (SELECT isbn FROM current_book WHERE id = 1)", (total,)
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # ── Fortschritts-Operationen ──────────────────────────────────────────────

    async def update_progress(self, user_id: int, guild_id: int, isbn: str,
                               mode: str, current: int,
                               total_override: int | None = None,
                               supplement_mode: str | None = None,
                               supplement_value: int | None = None,
                               completed: bool = False) -> None:
        """
        Lesefortschritt eines Users für ein bestimmtes Buch setzen oder aktualisieren.

        `completed` hält fest, dass das Buch damit zu Ende gelesen ist. Das Datum
        des ersten Abschlusses bleibt stehen; wer seinen Stand wieder nach unten
        korrigiert, gilt nicht mehr als fertig.
        """
        await self._conn.execute("""
            INSERT INTO reading_progress
                (user_id, guild_id, isbn, mode, current, total_override, supplement_mode, supplement_value,
                 updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), CASE WHEN ? THEN datetime('now') END)
            ON CONFLICT(user_id, guild_id, isbn) DO UPDATE SET
                mode=excluded.mode, current=excluded.current,
                total_override=COALESCE(excluded.total_override, total_override),
                supplement_mode=excluded.supplement_mode,
                supplement_value=excluded.supplement_value,
                updated_at=excluded.updated_at,
                completed_at=CASE WHEN excluded.completed_at IS NULL THEN NULL
                                  ELSE COALESCE(completed_at, excluded.completed_at) END
        """, (user_id, guild_id, isbn, mode, current, total_override, supplement_mode, supplement_value, completed))
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

        # Abgeschlossen ist ein Buch, das zu Ende gelesen wurde, auch das aktuelle.
        async with self._conn.execute("""
            SELECT COUNT(DISTINCT isbn) as cnt FROM reading_progress
            WHERE user_id = ? AND guild_id = ? AND completed_at IS NOT NULL AND isbn != ''
        """, (user_id, guild_id)) as cursor:
            cnt_row = await cursor.fetchone()
        books_completed = cnt_row["cnt"] if cnt_row else 0

        # zuletzt abgeschlossenes Buch
        async with self._conn.execute("""
            SELECT isbn, completed_at FROM reading_progress
            WHERE user_id = ? AND guild_id = ? AND completed_at IS NOT NULL AND isbn != ''
            ORDER BY completed_at DESC LIMIT 1
        """, (user_id, guild_id)) as cursor:
            last_row = await cursor.fetchone()
        last_isbn = last_row["isbn"] if last_row else None
        last_updated_at = last_row["completed_at"] if last_row else None

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

    # ── Leseziele ─────────────────────────────────────────────────────────────

    async def set_goal(self, user_id: int, guild_id: int, isbn: str, unit: str,
                       target: int, deadline: str, start_value: int, start_date: str) -> None:
        """Leseziel setzen oder ersetzen. Eine eingeschaltete Erinnerung bleibt bestehen."""
        await self._conn.execute("""
            INSERT INTO reading_goals (user_id, guild_id, isbn, unit, target, deadline, start_value, start_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id, isbn) DO UPDATE SET
                unit=excluded.unit, target=excluded.target, deadline=excluded.deadline,
                start_value=excluded.start_value, start_date=excluded.start_date,
                created_at=datetime('now')
        """, (user_id, guild_id, isbn, unit, target, deadline, start_value, start_date))
        await self._conn.commit()

    async def get_goal(self, user_id: int, guild_id: int, isbn: str) -> dict | None:
        async with self._conn.execute("""
            SELECT * FROM reading_goals WHERE user_id = ? AND guild_id = ? AND isbn = ?
        """, (user_id, guild_id, isbn)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def delete_goal(self, user_id: int, guild_id: int, isbn: str) -> bool:
        """Leseziel löschen. Die Erinnerung dazu verschwindet mit."""
        cursor = await self._conn.execute("""
            DELETE FROM reading_goals WHERE user_id = ? AND guild_id = ? AND isbn = ?
        """, (user_id, guild_id, isbn))
        await self._conn.commit()
        return cursor.rowcount > 0

    # ── Erinnerungen ──────────────────────────────────────────────────────────

    async def enable_reminder(self, user_id: int, guild_id: int, isbn: str, interval_days: int) -> None:
        """Erinnerung einschalten. Nur der Befehl des Mitglieds ruft das auf."""
        await self._conn.execute("""
            INSERT INTO reading_reminders (user_id, guild_id, isbn, interval_days)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, guild_id, isbn) DO UPDATE SET interval_days=excluded.interval_days
        """, (user_id, guild_id, isbn, interval_days))
        await self._conn.commit()

    async def disable_reminder(self, user_id: int, guild_id: int, isbn: str) -> bool:
        cursor = await self._conn.execute("""
            DELETE FROM reading_reminders WHERE user_id = ? AND guild_id = ? AND isbn = ?
        """, (user_id, guild_id, isbn))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def get_reminder(self, user_id: int, guild_id: int, isbn: str) -> dict | None:
        async with self._conn.execute("""
            SELECT * FROM reading_reminders WHERE user_id = ? AND guild_id = ? AND isbn = ?
        """, (user_id, guild_id, isbn)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_reminders(self, isbn: str) -> list[dict]:
        """Alle eingeschalteten Erinnerungen für ein Buch."""
        async with self._conn.execute(
            "SELECT * FROM reading_reminders WHERE isbn = ?", (isbn,)
        ) as cursor:
            return [dict(r) for r in await cursor.fetchall()]

    async def mark_reminder_sent(self, user_id: int, guild_id: int, isbn: str, sent_at: str) -> None:
        await self._conn.execute("""
            UPDATE reading_reminders SET last_sent_at = ?
            WHERE user_id = ? AND guild_id = ? AND isbn = ?
        """, (sent_at, user_id, guild_id, isbn))
        await self._conn.commit()

    # ── Sicherung ─────────────────────────────────────────────────────────────

    async def backup_to(self, target_path: str) -> None:
        """Vollständige Kopie über SQLites eigene Sicherung, auch während geschrieben wird."""
        async with aiosqlite.connect(target_path) as target:
            await self._conn.backup(target)

    # ── Bücherliste ───────────────────────────────────────────────────────────

    async def get_book_record(self, isbn: str) -> dict | None:
        async with self._conn.execute("SELECT * FROM books WHERE isbn = ?", (isbn,)) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def set_book_thread(self, isbn: str, thread_id: int) -> bool:
        cursor = await self._conn.execute("UPDATE books SET thread_id = ? WHERE isbn = ?", (thread_id, isbn))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def book_thread_ids(self) -> set[int]:
        async with self._conn.execute("SELECT thread_id FROM books WHERE thread_id IS NOT NULL") as cursor:
            return {row[0] for row in await cursor.fetchall()}

    async def book_readers(self, guild_id: int, isbn: str) -> list[int]:
        async with self._conn.execute(
            "SELECT user_id FROM reading_progress WHERE guild_id = ? AND isbn = ?", (guild_id, isbn)
        ) as cursor:
            return [row[0] for row in await cursor.fetchall()]

    # ── Kennzahlen für Achievements ───────────────────────────────────────────

    async def add_thread_message(self, user_id: int, guild_id: int, count: int = 1) -> None:
        await self._conn.execute("""
            INSERT INTO thread_messages (user_id, guild_id, count) VALUES (?, ?, ?)
            ON CONFLICT(user_id, guild_id) DO UPDATE SET count = count + excluded.count
        """, (user_id, guild_id, count))
        await self._conn.commit()

    async def record_goal_reached(self, user_id: int, guild_id: int, isbn: str, target: int,
                                  deadline: str, reached_at: str) -> bool:
        """Ein erreichtes Ziel einmal festhalten. True, wenn es neu ist."""
        cursor = await self._conn.execute("""
            INSERT OR IGNORE INTO goals_reached (user_id, guild_id, isbn, target, deadline, reached_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, guild_id, isbn, target, deadline, reached_at))
        await self._conn.commit()
        return cursor.rowcount > 0

    async def _scalar(self, sql: str, params: tuple) -> int:
        async with self._conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return (row[0] or 0) if row else 0

    async def achievement_stats(self, user_id: int, guild_id: int) -> dict:
        """Alle Kennzahlen, an denen Achievements und Ränge hängen."""
        who = (user_id, guild_id)
        stats = {
            "books_finished": await self._scalar("""
                SELECT COUNT(DISTINCT isbn) FROM reading_progress
                WHERE user_id = ? AND guild_id = ? AND completed_at IS NOT NULL AND isbn != ''
            """, who),
            "fortschritt_count": await self._scalar(
                "SELECT fortschritt_count FROM user_stats WHERE user_id = ? AND guild_id = ?", who
            ),
            "goals_reached_early": await self._scalar("""
                SELECT COUNT(*) FROM goals_reached
                WHERE user_id = ? AND guild_id = ? AND date(reached_at) <= deadline
            """, who),
            "thread_messages": await self._scalar(
                "SELECT count FROM thread_messages WHERE user_id = ? AND guild_id = ?", who
            ),
            # Als Erste·r fertig: das eigene Abschlussdatum ist das früheste bei diesem Clubbuch.
            "first_finishes": await self._scalar("""
                SELECT COUNT(*) FROM reading_progress p JOIN books b ON b.isbn = p.isbn
                WHERE p.user_id = ? AND p.guild_id = ? AND p.completed_at IS NOT NULL
                  AND p.completed_at = (SELECT MIN(q.completed_at) FROM reading_progress q
                                        WHERE q.guild_id = p.guild_id AND q.isbn = p.isbn)
            """, who),
            # Alle, die ein Clubbuch angefangen haben (mindestens zwei), sind fertig.
            "all_finished_books": await self._scalar("""
                SELECT COUNT(*) FROM reading_progress p JOIN books b ON b.isbn = p.isbn
                WHERE p.user_id = ? AND p.guild_id = ? AND p.completed_at IS NOT NULL
                  AND (SELECT COUNT(*) FROM reading_progress q WHERE q.guild_id = p.guild_id AND q.isbn = p.isbn) >= 2
                  AND NOT EXISTS (SELECT 1 FROM reading_progress q
                                  WHERE q.guild_id = p.guild_id AND q.isbn = p.isbn AND q.completed_at IS NULL)
            """, who),
        }

        pages = 0
        async with self._conn.execute("""
            SELECT p.*, b.total_pages AS book_pages, b.total_chapters AS book_chapters
            FROM reading_progress p LEFT JOIN books b ON b.isbn = p.isbn
            WHERE p.user_id = ? AND p.guild_id = ?
        """, who) as cursor:
            for row in map(dict, await cursor.fetchall()):
                book = {"total_pages": row["book_pages"], "total_chapters": row["book_chapters"]}
                total = row.get("total_override") or row["book_pages"]
                if row.get("completed_at") and total:
                    pages += total
                else:
                    pages += progress_in_unit(row, "pages", book) or 0
        stats["pages_read"] = pages
        return stats

    # ── Achievements ──────────────────────────────────────────────────────────

    async def get_achievements(self, user_id: int, guild_id: int) -> set[tuple[str, int]]:
        async with self._conn.execute(
            "SELECT key, tier FROM achievements WHERE user_id = ? AND guild_id = ?", (user_id, guild_id)
        ) as cursor:
            return {(row[0], row[1]) for row in await cursor.fetchall()}

    async def store_achievements(self, user_id: int, guild_id: int, items: set[tuple[str, int]],
                                 unlocked_at: str | None = None) -> list[tuple[str, int]]:
        """Speichert, was noch fehlt, und gibt nur das Neue zurück (sortiert)."""
        new = []
        for key, tier in sorted(items):
            cursor = await self._conn.execute("""
                INSERT OR IGNORE INTO achievements (user_id, guild_id, key, tier, unlocked_at)
                VALUES (?, ?, ?, ?, COALESCE(?, datetime('now')))
            """, (user_id, guild_id, key, tier, unlocked_at))
            if cursor.rowcount > 0:
                new.append((key, tier))
        await self._conn.commit()
        return new

    async def get_unseen(self, user_id: int, guild_id: int) -> list[tuple[str, int]]:
        async with self._conn.execute("""
            SELECT key, tier FROM achievements WHERE user_id = ? AND guild_id = ? AND seen = 0
            ORDER BY unlocked_at, key, tier
        """, (user_id, guild_id)) as cursor:
            return [(row[0], row[1]) for row in await cursor.fetchall()]

    async def mark_seen(self, user_id: int, guild_id: int) -> None:
        await self._conn.execute(
            "UPDATE achievements SET seen = 1 WHERE user_id = ? AND guild_id = ?", (user_id, guild_id)
        )
        await self._conn.commit()
