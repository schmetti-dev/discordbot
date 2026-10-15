"""
Leseziele: Rechnen ohne Discord und ohne Datenbank

Alles hier ist reine Logik mit festem Datum als Eingabe, damit jeder Fall
testbar ist. Die Cogs holen die Daten und zeigen das Ergebnis an.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta

UNIT_LABELS = {"pages": ("Seite", "Seiten"), "chapters": ("Kapitel", "Kapitel")}


def unit_label(unit: str, amount: int) -> str:
    singular, plural = UNIT_LABELS[unit]
    return singular if amount == 1 else plural


def progress_in_unit(progress: dict | None, unit: str, book: dict | None) -> int | None:
    """
    Stand eines Mitglieds in der Einheit des Ziels, oder None wenn er sich
    daraus nicht ablesen lässt (z.B. Ziel in Kapiteln, Stand nur in Prozent).
    """
    if not progress:
        return 0
    mode = progress["mode"]
    current = progress["current"]

    if unit == "chapters":
        return current if mode == "chapters" else None

    # unit == "pages"
    if mode == "pages":
        return current
    if mode == "chapters" and progress.get("supplement_mode") == "pages":
        return progress.get("supplement_value")

    total = progress.get("total_override") or (book.get("total_pages") if book else None)
    if not total:
        return None
    if mode == "percent":
        return round(total * current / 100)
    if mode == "chapters" and progress.get("supplement_mode") == "percent":
        return round(total * (progress.get("supplement_value") or 0) / 100)
    return None


def is_complete(mode: str, current: int, supplement_mode: str | None, supplement_value: int | None,
                total_pages: int | None, total_chapters: int | None) -> bool:
    """Ob dieser Stand das Ende des Buchs ist. Ohne bekannte Gesamtzahl zählt nur 100 %."""
    if mode == "percent":
        return current >= 100
    if supplement_mode == "percent" and supplement_value is not None and supplement_value >= 100:
        return True
    if mode == "pages":
        return bool(total_pages) and current >= total_pages
    if supplement_mode == "pages" and supplement_value is not None and total_pages and supplement_value >= total_pages:
        return True
    return bool(total_chapters) and current >= total_chapters


@dataclass(frozen=True)
class Pace:
    state: str            # 'reached' | 'overdue' | 'open'
    remaining: int        # noch zu lesen, nie negativ
    days_left: int        # Tage einschließlich heute, 0 wenn das Datum vorbei ist
    per_day: int          # nötig pro Tag, aufgerundet; 0 wenn erreicht oder überfällig
    behind: bool          # liegt hinter dem gleichmäßigen Tempo seit Zielbeginn


def compute_pace(goal: dict, current: int, today: date) -> Pace:
    """Was das Ziel heute bedeutet."""
    deadline = date.fromisoformat(goal["deadline"])
    start_date = date.fromisoformat(goal["start_date"])
    target = goal["target"]
    start_value = goal["start_value"]

    remaining = max(target - current, 0)
    if remaining == 0:
        return Pace("reached", 0, max((deadline - today).days + 1, 0), 0, False)
    if today > deadline:
        return Pace("overdue", remaining, 0, 0, True)

    days_left = (deadline - today).days + 1
    per_day = math.ceil(remaining / days_left)

    # Gleichmäßiges Tempo: am Ende jedes Tages ein gleicher Teil der Strecke.
    # Heute zählt erst morgen als Rückstand, sonst wäre man am ersten Tag sofort hinten.
    total_days = (deadline - start_date).days + 1
    days_done = min(max((today - start_date).days, 0), total_days)
    expected = start_value + (target - start_value) * days_done / total_days
    behind = current < math.floor(expected)

    return Pace("open", remaining, days_left, per_day, behind)


def reminder_is_due(
    reminder: dict,
    goal: dict | None,
    current: int | None,
    now: datetime,
    today: date,
) -> bool:
    """
    Ob jetzt eine Erinnerung rausgehen darf. `reminder` existiert nur, wenn das
    Mitglied sie selbst eingeschaltet hat; ohne Eintrag wird diese Funktion nie
    gefragt. Sie sagt zusätzlich nein, wenn es nichts zu erinnern gibt.
    """
    if goal is None or current is None:
        return False
    pace = compute_pace(goal, current, today)
    if pace.state != "open" or not pace.behind:
        return False
    last = reminder.get("last_sent_at")
    if last:
        if now - datetime.fromisoformat(last) < timedelta(days=reminder["interval_days"]):
            return False
    return True


def describe_pace(goal: dict, pace: Pace) -> str:
    """Ein Satz für das Mitglied. Freundlich, ohne Vorwurf."""
    unit = goal["unit"]
    deadline = date.fromisoformat(goal["deadline"]).strftime("%d.%m.%Y")
    if pace.state == "reached":
        return f"Ziel erreicht: {goal['target']} {unit_label(unit, goal['target'])}. Glückwunsch!"
    if pace.state == "overdue":
        return (
            f"Das Datum ({deadline}) ist vorbei, es fehlen noch {pace.remaining} "
            f"{unit_label(unit, pace.remaining)}. Mit `/leseziel setzen` kannst du ein neues Datum wählen."
        )
    tage = "Tag" if pace.days_left == 1 else "Tage"
    return (
        f"Noch {pace.remaining} {unit_label(unit, pace.remaining)} bis zum {deadline}, "
        f"das sind {pace.days_left} {tage}: **{pace.per_day} {unit_label(unit, pace.per_day)} am Tag**."
    )
