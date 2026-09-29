"""
Achievements und Ränge der Buchketiere

Der Katalog ist reine Daten, die Auswertung reine Funktionen: aus Kennzahlen
eines Mitglieds (Bücher, Einträge, Ziele, ...) ergibt sich, was es verdient hat.
Datenbank und Discord kommen erst in cogs/achievements.py dazu.

Achievements sind privat: jedes Mitglied sieht nur die eigenen.

Die Ränge folgen d'Artagnans Laufbahn in Dumas' Musketier-Romanen: junger
Gascogner, Gardist in der Kompanie des Essarts, Leutnant der Musketiere
(Patent vom Kardinal), Kapitän (Patent von Mazarin), Marschall von Frankreich.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

TIERS = ["holz", "bronze", "silber", "gold"]
TIER_LABELS = ["Holz", "Bronze", "Silber", "Gold"]


@dataclass(frozen=True)
class Achievement:
    key: str
    name: str
    icon: str                      # game-icons.net, Name des Icons
    kind: str                      # "tiered" | "single" | "secret"
    stat: str | None = None        # Kennzahl, an der Stufen oder Bedingung hängen
    thresholds: tuple[int, ...] = ()
    tier_names: tuple[str, ...] = ()
    text: str = ""                 # {n} = Kennzahl
    hint: str = ""                 # Wie man es bekommt; bei geheimen leer
    shared: str = ""               # Satz beim Teilen, {name} = Mitglied


CATALOGUE = [
    Achievement(
        "letzte_seite", "Bis zur letzten Seite", "open-book", "tiered", "books_finished", (1, 3, 10, 25),
        ("Das hölzerne Buch", "Das bronzene Buch", "Das silberne Buch", "Das goldene Buch"),
        "{n} {buch} bis zur letzten Seite gelesen. Auch das Nachwort? Wir fragen lieber nicht.",
        shared="{name} hat {n} {buch} bis zur letzten Seite gelesen. Ob auch das Nachwort, bleibt ein Geheimnis.",
    ),
    Achievement(
        "fleissig", "Fleißiges Buchketier", "quill-ink", "tiered", "fortschritt_count", (10, 50, 150, 500),
        text="{n}× /fortschritt. Du meldest dich öfter zum Rapport als jeder Gardist.",
        shared="{name} hat sich {n}× mit /fortschritt zum Rapport gemeldet.",
    ),
    Achievement(
        "streber", "Streber", "graduate-cap", "tiered", "goals_reached_early", (1, 3, 10, 25),
        text="{n} {ziel} vor dem Datum erreicht. Die Hausaufgaben sind sicher auch schon gemacht.",
        shared="{name} hat {n} {ziel} vor dem Datum erreicht. Streber!",
    ),
    Achievement(
        "plaudertasche", "Plaudertasche", "parrot-head", "tiered", "thread_messages", (25, 100, 250, 500),
        text="{n} Beiträge in den Buch-Threads. Mehr als manche Autoren in ihren Büchern.",
        shared="{name} hat {n} Beiträge in den Buch-Threads geschrieben. Mehr als manche Autoren in ihren Büchern.",
    ),
    Achievement(
        "seitenfresser", "Seitenfresser", "apple-maggot", "tiered", "pages_read", (500, 2000, 10000, 25000),
        ("Leseraupe", "Bücherwurm", "Büchernarr", "Großmeister der Seiten"),
        "{n} Seiten verschlungen.",
        shared="{name} hat {n} Seiten verschlungen.",
    ),
    Achievement(
        "gascogne", "Frisch aus der Gascogne", "horse-head", "single", "fortschritt_count", (1,),
        text="Dein erster Eintrag. Frisch in Paris, über dein Pferd wird noch gelacht.",
        hint="Trag zum ersten Mal deinen Fortschritt ein.",
        shared="{name} ist frisch aus der Gascogne angekommen. Über das Pferd wird noch gelacht.",
    ),
    Achievement(
        "schnellster_degen", "Schnellster Degen", "sword-brandish", "single", "first_finishes", (1,),
        text="Du hast ein Clubbuch als Erste·r ausgelesen.",
        hint="Lies ein Clubbuch als Erste·r aus.",
        shared="{name} hat ein Clubbuch als Erste·r ausgelesen. Schnellster Degen!",
    ),
    Achievement(
        "einer_fuer_alle", "Einer für alle", "crossed-swords", "single", "all_finished_books", (1,),
        text="Alle, die das Buch angefangen haben, haben es auch beendet. Einer für alle, alle für einen!",
        hint="Alle, die ein Clubbuch angefangen haben, lesen es auch zu Ende.",
        shared="Alle haben das Buch zu Ende gelesen, {name} war dabei. Einer für alle, alle für einen!",
    ),
    Achievement(
        "naechtlicher_ausritt", "Nächtlicher Ausritt", "owl", "single",
        text="Ein Eintrag zwischen Mitternacht und vier Uhr. Musketiere reiten auch nachts.",
        hint="Trag deinen Fortschritt zwischen Mitternacht und vier Uhr ein.",
        shared="{name} reitet auch nachts: ein Eintrag zwischen Mitternacht und vier Uhr.",
    ),
    Achievement(
        "gewaltritt", "Gewaltritt", "cloaked-figure-on-horseback", "single",
        text="Ein Viertel des Buchs an einem Tag. Das Pferd braucht jetzt eine Pause.",
        hint="Lies ein Viertel eines Buchs innerhalb von 24 Stunden.",
        shared="{name} hat ein Viertel des Buchs an einem Tag gelesen. Das Pferd braucht eine Pause.",
    ),
    Achievement(
        "diamantspangen", "Die zwölf Diamantspangen", "gem-pendant", "secret", "books_finished", (12,),
        text="Zwölf Bücher, zwölf Spangen. Diesmal fehlen keine zwei.",
        shared="{name} hat zwölf Bücher ausgelesen. Die zwölf Diamantspangen sind vollzählig.",
    ),
    Achievement(
        "freibrief", "Freibrief des Kardinals", "wax-seal", "secret",
        text="Du liest nebenher ein eigenes Buch. Mit Freibrief, versteht sich.",
        shared="{name} liest mit Freibrief des Kardinals ein eigenes Buch nebenher.",
    ),
]
BY_KEY = {a.key: a for a in CATALOGUE}

# Rang nach ausgelesenen Büchern: (ab Büchern, Name, Farbe, Satz zur Beförderung)
RANKS = [
    (0, "Gascogner", 0x8B6B3D, "Frisch in Paris, über das Pferd wird noch gelacht."),
    (1, "Gardist bei des Essarts", 0x6A8759, "Noch kein Buchketier, aber schon in Uniform."),
    (3, "Buchketier", 0x4A90D9, "Einer für alle, alle für ein Buch."),
    (7, "Leutnant der Buchketiere", 0xD4A017, "Das Patent unterschreibt der Kardinal persönlich."),
    (12, "Kapitän der Buchketiere", 0xC0392B, "Diesmal zeichnet Mazarin."),
    (20, "Marschall von Frankreich", 0x2C3E50, "Höher geht es nicht."),
]
RANK_KEY = "rang"


def rank_index(books_finished: int) -> int:
    index = 0
    for i, (threshold, *_rest) in enumerate(RANKS):
        if books_finished >= threshold:
            index = i
    return index


def rank_for(books_finished: int) -> tuple[str, int]:
    _, name, color, _ = RANKS[rank_index(books_finished)]
    return name, color


def next_rank(books_finished: int) -> tuple[str, int] | None:
    """(Name des nächsten Rangs, noch fehlende Bücher) oder None beim höchsten Rang."""
    for threshold, name, _, _ in RANKS:
        if books_finished < threshold:
            return name, threshold - books_finished
    return None


def earned(stats: dict) -> set[tuple[str, int]]:
    """
    Alles, was diese Kennzahlen hergeben, als (key, tier). Gestufte haben die
    Stufen 1 bis 4 (jede erreichte Stufe einzeln), einmalige die Stufe 0.
    Achievements aus Ereignissen (Uhrzeit, Tempo) stehen nicht in Kennzahlen,
    die liefert event_unlocks.
    """
    result: set[tuple[str, int]] = set()
    for achievement in CATALOGUE:
        if not achievement.stat:
            continue
        value = stats.get(achievement.stat, 0)
        if achievement.kind == "tiered":
            for tier, threshold in enumerate(achievement.thresholds, start=1):
                if value >= threshold:
                    result.add((achievement.key, tier))
        elif value >= achievement.thresholds[0]:
            result.add((achievement.key, 0))
    for index in range(1, rank_index(stats.get("books_finished", 0)) + 1):
        result.add((RANK_KEY, index))
    return result


def book_fraction(progress: dict | None, book: dict | None) -> float | None:
    """Anteil des Buchs zwischen 0 und 1, oder None wenn er sich nicht bestimmen lässt."""
    if not progress:
        return 0.0
    mode, current = progress["mode"], progress["current"]
    supplement_mode, supplement_value = progress.get("supplement_mode"), progress.get("supplement_value")
    pages = progress.get("total_override") or (book or {}).get("total_pages")
    chapters = (book or {}).get("total_chapters")
    if mode == "percent":
        return min(current / 100, 1.0)
    if supplement_mode == "percent" and supplement_value is not None:
        return min(supplement_value / 100, 1.0)
    if mode == "pages" and pages:
        return min(current / pages, 1.0)
    if supplement_mode == "pages" and supplement_value is not None and pages:
        return min(supplement_value / pages, 1.0)
    if mode == "chapters" and chapters:
        return min(current / chapters, 1.0)
    return None


def event_unlocks(
    previous: dict | None,
    new: dict,
    book: dict | None,
    local_time: datetime,
    now: datetime,
    is_club_book: bool,
) -> set[str]:
    """
    Einmalige Achievements, die an einem einzelnen Eintrag hängen.

    previous/new: Fortschritt vor und nach dem Eintrag (previous mit updated_at),
    local_time: Uhrzeit des Eintrags beim Club, now: derselbe Zeitpunkt in UTC.
    """
    keys: set[str] = set()
    if 0 <= local_time.hour < 4:
        keys.add("naechtlicher_ausritt")
    if not is_club_book:
        keys.add("freibrief")
    if previous and previous.get("updated_at"):
        before = book_fraction(previous, book)
        after = book_fraction(new, book)
        then = datetime.fromisoformat(previous["updated_at"].replace(" ", "T"))
        if then.tzinfo is None and now.tzinfo is not None:
            then = then.replace(tzinfo=now.tzinfo)
        if before is not None and after is not None and now - then <= timedelta(hours=24) and after - before >= 0.25:
            keys.add("gewaltritt")
    return keys


def tier_label(achievement: Achievement, tier: int) -> str:
    if achievement.kind != "tiered":
        return ""
    if achievement.tier_names:
        return achievement.tier_names[tier - 1]
    return TIER_LABELS[tier - 1]


def badge_file(key: str, tier: int) -> str:
    """Dateiname des Abzeichens in assets/badges."""
    if key == RANK_KEY:
        return "rang.png"
    achievement = BY_KEY[key]
    return f"{key}-{TIERS[tier - 1]}.png" if achievement.kind == "tiered" else f"{key}.png"


def unlock_title(key: str, tier: int) -> str:
    if key == RANK_KEY:
        return f"Beförderung: {RANKS[tier][1]}"
    achievement = BY_KEY[key]
    label = tier_label(achievement, tier)
    return f"{achievement.name} · {label}" if label else achievement.name


def unlock_text(key: str, tier: int, stats: dict) -> str:
    if key == RANK_KEY:
        return RANKS[tier][3]
    achievement = BY_KEY[key]
    value = stats.get(achievement.stat, 0) if achievement.stat else 0
    return achievement.text.format(
        n=value,
        buch="Buch" if value == 1 else "Bücher",
        ziel="Leseziel" if value == 1 else "Leseziele",
    )


def share_text(key: str, tier: int, stats: dict, name: str) -> str:
    """Der öffentliche Satz, wenn ein Mitglied ein Achievement teilt."""
    if key == RANK_KEY:
        return f"{name} wurde befördert: **{RANKS[tier][1]}**. {RANKS[tier][3]}"
    achievement = BY_KEY[key]
    value = stats.get(achievement.stat, 0) if achievement.stat else 0
    # Bei gestuften zählt die Schwelle der geteilten Stufe, nicht der heutige Stand.
    if achievement.kind == "tiered":
        value = achievement.thresholds[tier - 1]
    return achievement.shared.format(
        name=name,
        n=value,
        buch="Buch" if value == 1 else "Bücher",
        ziel="Leseziel" if value == 1 else "Leseziele",
    )


def overview(stats: dict, unlocked: set[tuple[str, int]]) -> list[tuple[str, str]]:
    """
    Zeilen für /achievements: (Titel, Text). Gestufte zeigen Stufe und den Weg
    zur nächsten, geheime bleiben ??? bis freigeschaltet.
    """
    lines: list[tuple[str, str]] = []
    for achievement in CATALOGUE:
        value = stats.get(achievement.stat, 0) if achievement.stat else None
        if achievement.kind == "tiered":
            tiers = sorted(t for k, t in unlocked if k == achievement.key)
            top = tiers[-1] if tiers else 0
            title = f"{achievement.name} · {tier_label(achievement, top)}" if top else achievement.name
            if top < len(achievement.thresholds):
                nxt = achievement.thresholds[top]
                label = tier_label(achievement, top + 1)
                text = f"{value} von {nxt} bis {label}"
            else:
                text = f"{value}, höchste Stufe erreicht"
            lines.append(((("🏅 " if top else "▫️ ") + title), text))
        elif (achievement.key, 0) in unlocked:
            lines.append((f"🏅 {achievement.name}", unlock_text(achievement.key, 0, stats)))
        elif achievement.kind == "secret":
            lines.append(("▫️ ???", "Geheim. Wird verraten, wenn du es freischaltest."))
        else:
            lines.append((f"▫️ {achievement.name}", achievement.hint))
    return lines


def badge_specs() -> list[dict]:
    """Jedes Abzeichen mit Dateiname, Icon und Stil, für tools/badges/render.ts."""
    specs = []
    for achievement in CATALOGUE:
        if achievement.kind == "tiered":
            for tier, style in enumerate(TIERS, start=1):
                specs.append({"file": badge_file(achievement.key, tier), "icon": achievement.icon, "style": style})
        else:
            style = "geheim" if achievement.kind == "secret" else "einmalig"
            specs.append({"file": badge_file(achievement.key, 0), "icon": achievement.icon, "style": style})
    specs.append({"file": badge_file(RANK_KEY, 1), "icon": "fleur-de-lys", "style": "gold"})
    return specs


if __name__ == "__main__":
    import json

    print(json.dumps(badge_specs()))
