# 📚 Die Buchketiere — Discord Bot

Ein Discord-Bot für unseren Buchclub — gebaut mit [discord.py](https://discordpy.readthedocs.io/).

## Features

- 📖 **Aktuelles Buch** verwalten via ISBN (OpenLibrary API)
- 📝 **Klappentext & Cover** auf Knopfdruck anzeigen
- 📊 **Lesefortschritt** pro User tracken (Seiten oder Kapitel)
- 👥 **Übersicht** — wer ist wie weit?
- 🎯 **Leseziele** — ein Datum fürs ganze Buch oder bis zu einer Seite / einem Kapitel, mit dem nötigen Tempo pro Tag
- 🔔 **Erinnerungen** — privat, selten, und nur für Mitglieder, die sie selbst einschalten
- 💾 **Tägliche Sicherung** der Datenbank

## Commands

| Command | Beschreibung | Berechtigung |
|---|---|---|
| `/buch-setzen <isbn>` | Aktuelles Buch via ISBN setzen | Admin |
| `/set-total-chapters <n>` | Kapitelanzahl manuell setzen | Admin |
| `/buch` | Buchinfo + Klappentext anzeigen | Alle |
| `/fortschritt` | Eigenen Lesefortschritt aktualisieren | Alle |
| `/buchketiere` | Lesefortschritt aller Mitglieder | Alle |
| `/buchketier [mitglied]` | Leserprofil anzeigen | Alle |
| `/leseziel setzen <datum> [bis_seite] [bis_kapitel]` | Eigenes Leseziel setzen | Alle |
| `/leseziel zeigen` | Ziel und nötiges Tempo anzeigen | Alle |
| `/leseziel loeschen` | Ziel entfernen | Alle |
| `/erinnerung an [alle_tage]` | Private Erinnerung einschalten | Alle |
| `/erinnerung aus` | Erinnerung ausschalten | Alle |

### Leseziele und Erinnerungen

Ein Leseziel gehört dem Mitglied allein. Alle Antworten auf `/leseziel` und `/erinnerung` sieht nur, wer den Befehl getippt hat.

- Ohne weitere Angabe gilt das Ziel fürs ganze Buch. Mit `bis_seite` oder `bis_kapitel` gilt es bis zu dieser Stelle.
- Der Bot rechnet aus, wie viel pro Tag nötig ist, und rundet auf.
- **Eine Erinnerung bekommt nur, wer `/erinnerung an` ausführt.** Ein Ziel allein löst nie eine aus.
- Erinnerungen kommen als Direktnachricht, zwischen 9 und 20 Uhr, höchstens im gewählten Abstand (Standard: alle 7 Tage) und nur, wenn man hinter dem gleichmäßigen Tempo liegt.
- Sie hören auf, sobald das Ziel erreicht, gelöscht oder das Datum vorbei ist.

## Setup

### Voraussetzungen

- Python 3.11+
- Ein Discord Bot Token ([Discord Developer Portal](https://discord.com/developers/applications))

### Installation

```bash
# Repository klonen
git clone <repo-url>
cd discordbot

# Virtual Environment erstellen
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# Abhängigkeiten installieren
pip install -r requirements.txt   # gepinnte Versionen, erzeugt aus requirements.in

# .env anlegen
cp .env.example .env
# DISCORD_TOKEN in .env eintragen

# Bot starten
python bot.py
```

### Betrieb auf einem NAS oder Docker-Host

```bash
cd deploy/nas
cp .env.example .env      # Token, Server-ID und Sicherungsziel eintragen
docker compose up -d --build
```

Die Datenbank liegt in `DATA_DIR`, die tägliche Sicherung in `BACKUP_HOST_DIR`. Beide Verzeichnisse müssen der Kennung 1000 gehören, unter der der Bot im Container läuft. Leg die Sicherung auf eine andere Platte als die Datenbank.

Schreibt der Bot beim Start `Sicherung fehlgeschlagen` ins Log, darf er nicht in das Sicherungsverzeichnis schreiben. Manche NAS-Freigaben erlauben das nur einer Gruppe: trag deren Nummer als `EXTRA_GID` in `.env` ein.

### Sicherung und Wiederherstellung

Ist `BACKUP_DIR` gesetzt, schreibt der Bot beim Start und danach alle 24 Stunden eine vollständige Kopie der Datenbank (`buchclub-<Zeitpunkt>.db`), prüft sie mit SQLites Integritätsprüfung und behält die letzten `BACKUP_KEEP` Kopien. Ohne `BACKUP_DIR` gibt es keine Sicherung, und der Bot sagt das beim Start im Log.

Wiederherstellen:

```bash
docker compose down
cp /pfad/zur/sicherung/buchclub-<Zeitpunkt>.db data/buchclub.db
docker compose up -d
```

### Schema-Änderungen

Änderungen am Datenbankschema sind nummerierte Migrationen in `migrations.py`. Jede läuft genau einmal, festgehalten in der Tabelle `schema_version`. Eine neue Änderung kommt als neuer Eintrag ans Ende der Liste; bestehende Einträge werden nicht verändert.

### Tests ausführen

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Projektstruktur

```
discordbot/
├── bot.py              # Einstiegspunkt & Bot-Initialisierung
├── database.py         # Datenbankzugriff
├── migrations.py       # Nummerierte Schema-Migrationen
├── cogs/
│   ├── books.py        # /buch, /buch-setzen, /set-total-chapters
│   ├── progress.py     # /fortschritt, /buchketiere
│   ├── profiles.py     # /buchketier
│   └── goals.py        # /leseziel, /erinnerung
├── services/
│   ├── openlibrary.py  # OpenLibrary API Client
│   ├── goals.py        # Tempo und Fälligkeit, reine Logik
│   └── backup.py       # Tägliche Sicherung
├── tests/
│   ├── test_database.py    # Datenbank-Tests (in-memory SQLite)
│   ├── test_openlibrary.py # API-Tests (httpx Mock)
│   ├── test_goals.py       # Leseziele und Erinnerungen
│   └── test_migrations.py  # Migrationen und Sicherung
├── deploy/nas/         # Dockerfile und compose.yaml für NAS / Docker-Host
├── .env.example        # Vorlage für Umgebungsvariablen
├── requirements.in     # Produktions-Abhängigkeiten
├── requirements.txt    # Daraus erzeugt, gepinnt (uv pip compile)
└── requirements-dev.txt # Test-Abhängigkeiten
```

## Technologie

- **[discord.py](https://github.com/Rapptz/discord.py)** — Discord API Wrapper
- **aiosqlite** — Asynchrones SQLite
- **httpx** — Async HTTP Client (OpenLibrary API)
- **python-dotenv** — .env Datei laden
- **pytest + pytest-asyncio** — Async Tests
