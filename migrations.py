"""
Schema-Migrationen

Jede Migration hat eine Nummer und läuft genau einmal. Welche schon gelaufen
sind, steht in der Tabelle `schema_version`. Neue Schemaänderungen kommen als
neuer Eintrag ans Ende der Liste, bestehende Einträge werden nie verändert.
"""

import logging

import aiosqlite

log = logging.getLogger("buchclub.migrations")


async def _baseline(conn: aiosqlite.Connection) -> None:
    """Schema bis einschließlich v1.1.0, auch für Datenbanken aus älteren Versionen."""
    await conn.executescript("""
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

    # Ältere Datenbanken: reading_progress ohne 'percent', Zusatzangaben oder isbn.
    async with conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='reading_progress'"
    ) as cursor:
        row = await cursor.fetchone()
    async with conn.execute("PRAGMA table_info(reading_progress)") as cursor:
        columns = [r[1] for r in await cursor.fetchall()]

    if row and ("'percent'" not in row[0] or "supplement_mode" not in row[0]):
        has_isbn = "isbn" in columns
        isbn_source = "isbn" if has_isbn else "COALESCE((SELECT isbn FROM current_book WHERE id = 1), '')"
        await conn.executescript(f"""
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
            INSERT INTO reading_progress_new (user_id, guild_id, isbn, mode, current, total_override, updated_at)
                SELECT user_id, guild_id, {isbn_source}, mode, current, total_override, updated_at
                FROM reading_progress;
            DROP TABLE reading_progress;
            ALTER TABLE reading_progress_new RENAME TO reading_progress;
        """)
    elif "isbn" not in columns:
        await conn.execute("ALTER TABLE reading_progress ADD COLUMN isbn TEXT NOT NULL DEFAULT ''")
        await conn.execute("""
            UPDATE reading_progress
            SET isbn = COALESCE((SELECT isbn FROM current_book WHERE id = 1), '')
            WHERE isbn = ''
        """)


async def _goals_and_reminders(conn: aiosqlite.Connection) -> None:
    """Leseziele und Erinnerungen. Eine Erinnerung gibt es nur, wenn jemand sie einschaltet."""
    await conn.executescript("""
        CREATE TABLE reading_goals (
            user_id     INTEGER NOT NULL,
            guild_id    INTEGER NOT NULL,
            isbn        TEXT    NOT NULL,
            unit        TEXT    NOT NULL CHECK (unit IN ('pages', 'chapters')),
            target      INTEGER NOT NULL CHECK (target > 0),
            deadline    TEXT    NOT NULL,   -- Datum, JJJJ-MM-TT
            start_value INTEGER NOT NULL DEFAULT 0,
            start_date  TEXT    NOT NULL,   -- Datum, JJJJ-MM-TT
            created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, guild_id, isbn)
        );

        CREATE TABLE reading_reminders (
            user_id       INTEGER NOT NULL,
            guild_id      INTEGER NOT NULL,
            isbn          TEXT    NOT NULL,
            interval_days INTEGER NOT NULL CHECK (interval_days BETWEEN 1 AND 30),
            last_sent_at  TEXT,             -- Zeitpunkt in UTC, ISO 8601
            created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, guild_id, isbn),
            FOREIGN KEY (user_id, guild_id, isbn)
                REFERENCES reading_goals (user_id, guild_id, isbn) ON DELETE CASCADE
        );
    """)


async def _completed_at(conn: aiosqlite.Connection) -> None:
    """
    Merkt sich, wann ein Buch zu Ende gelesen wurde. Vorher galt jedes frühere
    Buch mit irgendeinem Eintrag als abgeschlossen, auch ein abgebrochenes.
    """
    await conn.execute("ALTER TABLE reading_progress ADD COLUMN completed_at TEXT")
    # Bestehende Einträge: sicher abgeschlossen ist, wer 100 % eingetragen hat ...
    await conn.execute("""
        UPDATE reading_progress SET completed_at = updated_at
        WHERE (mode = 'percent' AND current >= 100)
           OR (supplement_mode = 'percent' AND supplement_value >= 100)
    """)
    # ... oder beim aktuellen Buch die letzte Seite oder das letzte Kapitel erreicht hat.
    await conn.execute("""
        UPDATE reading_progress SET completed_at = updated_at
        WHERE completed_at IS NULL AND isbn = (SELECT isbn FROM current_book WHERE id = 1) AND (
            (mode = 'pages' AND current >= COALESCE(total_override, (SELECT total_pages FROM current_book WHERE id = 1)))
         OR (mode = 'chapters' AND current >= (SELECT total_chapters FROM current_book WHERE id = 1))
        )
    """)


async def _achievements(conn: aiosqlite.Connection) -> None:
    """Bücherliste mit Thread, Achievements, erreichte Ziele und Beiträge in Buch-Threads."""
    await conn.executescript("""
        -- Jedes Clubbuch, auch vergangene: Seiten für Seitenfresser, Thread für Plaudertasche.
        CREATE TABLE books (
            isbn           TEXT PRIMARY KEY,
            title          TEXT NOT NULL,
            total_pages    INTEGER,
            total_chapters INTEGER,
            set_at         TEXT,
            thread_id      INTEGER
        );
        INSERT INTO books (isbn, title, total_pages, total_chapters, set_at)
            SELECT isbn, title, total_pages, total_chapters, set_at FROM current_book;

        -- Freigeschaltete Achievements, je Stufe eine Zeile. seen = dem Mitglied schon gezeigt.
        CREATE TABLE achievements (
            user_id     INTEGER NOT NULL,
            guild_id    INTEGER NOT NULL,
            key         TEXT    NOT NULL,
            tier        INTEGER NOT NULL DEFAULT 0,
            unlocked_at TEXT    NOT NULL DEFAULT (datetime('now')),
            seen        INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, guild_id, key, tier)
        );

        -- Jedes erreichte Leseziel bleibt gezählt, auch wenn später ein neues gesetzt wird.
        CREATE TABLE goals_reached (
            user_id    INTEGER NOT NULL,
            guild_id   INTEGER NOT NULL,
            isbn       TEXT    NOT NULL,
            target     INTEGER NOT NULL,
            deadline   TEXT    NOT NULL,
            reached_at TEXT    NOT NULL,
            PRIMARY KEY (user_id, guild_id, isbn, target, deadline)
        );

        CREATE TABLE thread_messages (
            user_id  INTEGER NOT NULL,
            guild_id INTEGER NOT NULL,
            count    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, guild_id)
        );
    """)


MIGRATIONS = [
    (1, "Grundschema bis v1.1.0", _baseline),
    (2, "Leseziele und Erinnerungen", _goals_and_reminders),
    (3, "Abschlussdatum am Lesefortschritt", _completed_at),
    (4, "Achievements", _achievements),
]


async def migrate(conn: aiosqlite.Connection) -> list[int]:
    """Führt alle noch nicht gelaufenen Migrationen aus und gibt ihre Nummern zurück."""
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version    INTEGER PRIMARY KEY,
            name       TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    async with conn.execute("SELECT version FROM schema_version") as cursor:
        done = {row[0] for row in await cursor.fetchall()}

    applied = []
    for version, name, step in MIGRATIONS:
        if version in done:
            continue
        await step(conn)
        await conn.execute("INSERT INTO schema_version (version, name) VALUES (?, ?)", (version, name))
        await conn.commit()
        log.info(f"Migration {version} angewendet: {name}")
        applied.append(version)
    return applied
