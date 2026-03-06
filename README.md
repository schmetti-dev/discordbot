# 📚 Die Buchketiere — Discord Bot

Ein Discord-Bot für unseren Buchclub — gebaut mit [discord.py](https://discordpy.readthedocs.io/).

## Features

- 📖 **Aktuelles Buch** verwalten via ISBN (OpenLibrary API)
- 📝 **Klappentext & Cover** auf Knopfdruck anzeigen
- 📊 **Lesefortschritt** pro User tracken (Seiten oder Kapitel)
- 👥 **Übersicht** — wer ist wie weit?

## Commands

| Command | Beschreibung | Berechtigung |
|---|---|---|
| `/buch-setzen <isbn>` | Aktuelles Buch via ISBN setzen | Admin |
| `/set-total-chapters <n>` | Kapitelanzahl manuell setzen | Admin |
| `/buch` | Buchinfo + Klappentext anzeigen | Alle |
| `/fortschritt` | Eigenen Lesefortschritt aktualisieren | Alle |
| `/buchketiere` | Lesefortschritt aller Mitglieder | Alle |

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
pip install -r requirements.txt

# .env anlegen
cp .env.example .env
# DISCORD_TOKEN in .env eintragen

# Bot starten
python bot.py
```

### Tests ausführen

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Projektstruktur

```
discordbot/
├── bot.py              # Einstiegspunkt & Bot-Initialisierung
├── database.py         # SQLite Schema und Datenbankzugriff
├── cogs/
│   ├── books.py        # /buch, /buch-setzen, /set-total-chapters
│   └── progress.py     # /fortschritt, /buchketiere
├── services/
│   └── openlibrary.py  # OpenLibrary API Client
├── tests/
│   ├── test_database.py    # Datenbank-Tests (in-memory SQLite)
│   └── test_openlibrary.py # API-Tests (httpx Mock)
├── .env.example        # Vorlage für Umgebungsvariablen
├── requirements.txt    # Produktions-Abhängigkeiten
└── requirements-dev.txt # Test-Abhängigkeiten
```

## Technologie

- **[discord.py](https://github.com/Rapptz/discord.py)** — Discord API Wrapper
- **aiosqlite** — Asynchrones SQLite
- **httpx** — Async HTTP Client (OpenLibrary API)
- **python-dotenv** — .env Datei laden
- **pytest + pytest-asyncio** — Async Tests
