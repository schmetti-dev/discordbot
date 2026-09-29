# Abzeichen

Die Icons in `icons/` stammen von [game-icons.net](https://game-icons.net) und stehen unter
[CC BY 3.0](https://creativecommons.org/licenses/by/3.0/) (Lizenz laut Iconify-Sammlung
`game-icons`). Rahmen und Farben der Abzeichen sind eigene Arbeit.

Neu zeichnen (braucht bun):

```bash
.venv/bin/python -m services.achievements | bun tools/badges/render.ts
```

Das schreibt alle PNGs nach `assets/badges/`. Ein neues Achievement braucht nur einen Eintrag
im Katalog (`services/achievements.py`) und sein Icon als SVG in `icons/`, z.B. von
`https://api.iconify.design/game-icons/<name>.svg`.
