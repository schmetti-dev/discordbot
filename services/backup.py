"""
Tägliche Sicherung der Datenbank

Schreibt eine vollständige Kopie in ein zweites Verzeichnis (eigenes Volume,
am besten auf einer anderen Platte) und behält die letzten Kopien.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("buchclub.backup")

PREFIX = "buchclub-"
SUFFIX = ".db"


def backup_dir() -> Path | None:
    """Zielverzeichnis aus BACKUP_DIR, oder None wenn keine Sicherung eingerichtet ist."""
    value = os.getenv("BACKUP_DIR", "").strip()
    return Path(value) if value else None


def keep_count() -> int:
    return max(int(os.getenv("BACKUP_KEEP", "14")), 1)


def verify(path: Path) -> bool:
    """Prüft die Kopie mit SQLites eigener Integritätsprüfung."""
    connection = sqlite3.connect(path)
    try:
        return connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        connection.close()


def prune(directory: Path, keep: int) -> list[Path]:
    """Löscht alles bis auf die `keep` neuesten Kopien und gibt die gelöschten zurück."""
    copies = sorted(directory.glob(f"{PREFIX}*{SUFFIX}"))
    removed = copies[:-keep] if len(copies) > keep else []
    for path in removed:
        path.unlink()
    return removed


async def run_backup(db, now: datetime | None = None) -> Path | None:
    """Eine Sicherung schreiben, prüfen, alte aufräumen. Gibt den Pfad der Kopie zurück."""
    directory = backup_dir()
    if directory is None:
        return None
    directory.mkdir(parents=True, exist_ok=True)

    stamp = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H-%M-%SZ")
    target = directory / f"{PREFIX}{stamp}{SUFFIX}"
    await db.backup_to(str(target))

    if not verify(target):
        # Eine kaputte Kopie ist schlimmer als keine: sie sieht aus wie eine Sicherung.
        target.unlink(missing_ok=True)
        raise RuntimeError(f"Sicherung {target.name} hat die Integritätsprüfung nicht bestanden.")

    prune(directory, keep_count())
    log.info(f"Sicherung geschrieben: {target.name}")
    return target
