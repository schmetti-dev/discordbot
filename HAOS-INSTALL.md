# Buchclub Bot als Home Assistant Add-on installieren

## Voraussetzungen

- Home Assistant OS (HAOS) auf Raspberry Pi 5
- Zugang zur HA Web-UI
- Bot-Repo auf GitHub gepusht (öffentlich oder mit Zugriffstoken)

## Schritt 1: Repo-URL in `repository.yaml` setzen

Bearbeite `repository.yaml` im Repo-Root und trage deine GitHub-URL ein:

```yaml
url: "https://github.com/schmetti-dev/discordbot"
```

## Schritt 2: Code auf GitHub pushen

```bash
git add .
git commit -m "feat: Add Home Assistant add-on files"
git push
```

## Schritt 3: Repository in Home Assistant hinzufügen

1. **HA Web-UI** öffnen
2. **Einstellungen → Add-ons → Add-on Store** (Button unten rechts: ⋮)
3. **„Repositories"** wählen
4. GitHub-URL eintragen: `https://github.com/DEIN_USERNAME/discordbot`
5. **„Hinzufügen"** klicken — Seite neu laden

## Schritt 4: Add-on installieren

1. Im Add-on Store erscheint jetzt **„Buchclub Discord Bot"**
2. Add-on öffnen → **„Installieren"**
3. Unter **„Konfiguration"** eintragen:
   - `discord_token`: Dein Bot-Token
   - `discord_guild_id`: Deine Server-ID (optional, für Dev-Modus)
   - `admin_role_name`: Name der Admin-Rolle (Standard: `Buchclub-Admin`)
4. **„Starten"** klicken

## Lokale Entwicklung

Für lokale Entwicklung `.env` Datei anlegen:

```env
DISCORD_TOKEN=dein_token
DISCORD_GUILD_ID=deine_server_id
ADMIN_ROLE_NAME=Buchclub-Admin
DB_PATH=buchclub.db
```

`DB_PATH=buchclub.db` sorgt dafür, dass die SQLite-Datenbank lokal statt im HA-Datenpfad `/data/` liegt.

## Add-on aktualisieren

Nach Code-Änderungen:

```bash
git add .
git commit -m "..."
git push
```

In HA: Add-on → **„Aktualisieren"** (erscheint wenn neue Version in `config.yaml` gesetzt).
