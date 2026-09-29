"""
Tests für Leseziele und Erinnerungen

Die Logik rechnet mit festem Datum, deshalb läuft hier nichts gegen die Uhr
und nichts gegen Discord.
"""

from datetime import date, datetime, timedelta, timezone

import discord
import pytest

from cogs.goals import parse_date, send_due_reminders
from database import Database
from services.goals import compute_pace, describe_pace, is_complete, progress_in_unit, reminder_is_due

ISBN = "9783453319875"
GUILD = 999
BOOK = {"isbn": ISBN, "title": "Der Schwarm", "total_pages": 1000, "total_chapters": 20}


def goal(target=1000, unit="pages", deadline="2026-10-31", start_value=0, start_date="2026-10-01"):
    return {"unit": unit, "target": target, "deadline": deadline, "start_value": start_value, "start_date": start_date}


# ── Stand in der Einheit des Ziels ────────────────────────────────────────────

def test_progress_without_entry_is_zero():
    assert progress_in_unit(None, "pages", BOOK) == 0


def test_progress_pages_for_pages_goal():
    assert progress_in_unit({"mode": "pages", "current": 142}, "pages", BOOK) == 142


def test_progress_percent_converts_to_pages():
    assert progress_in_unit({"mode": "percent", "current": 46}, "pages", BOOK) == 460


def test_progress_percent_uses_personal_page_count():
    progress = {"mode": "percent", "current": 50, "total_override": 320}
    assert progress_in_unit(progress, "pages", BOOK) == 160


def test_progress_chapters_with_page_supplement():
    progress = {"mode": "chapters", "current": 5, "supplement_mode": "pages", "supplement_value": 210}
    assert progress_in_unit(progress, "pages", BOOK) == 210
    assert progress_in_unit(progress, "chapters", BOOK) == 5


def test_progress_not_readable_in_other_unit():
    assert progress_in_unit({"mode": "pages", "current": 142}, "chapters", BOOK) is None
    assert progress_in_unit({"mode": "chapters", "current": 5}, "pages", BOOK) is None
    assert progress_in_unit({"mode": "percent", "current": 46}, "pages", {"isbn": ISBN}) is None


# ── Tempo ─────────────────────────────────────────────────────────────────────

def test_pace_whole_book():
    pace = compute_pace(goal(), current=0, today=date(2026, 10, 1))
    assert (pace.state, pace.remaining, pace.days_left, pace.per_day) == ("open", 1000, 31, 33)


def test_pace_rounds_up():
    pace = compute_pace(goal(target=10, deadline="2026-10-03"), current=0, today=date(2026, 10, 1))
    assert pace.per_day == 4  # 10 in 3 Tagen: 3 am Tag würden nicht reichen


def test_pace_last_day_counts_as_one_day():
    pace = compute_pace(goal(target=300), current=280, today=date(2026, 10, 31))
    assert (pace.state, pace.days_left, pace.per_day) == ("open", 1, 20)


def test_pace_reached_exactly_and_beyond():
    assert compute_pace(goal(target=300), current=300, today=date(2026, 10, 10)).state == "reached"
    beyond = compute_pace(goal(target=300), current=350, today=date(2026, 10, 10))
    assert (beyond.state, beyond.remaining, beyond.behind) == ("reached", 0, False)


def test_pace_reached_stays_reached_after_deadline():
    assert compute_pace(goal(target=300), current=300, today=date(2026, 11, 5)).state == "reached"


def test_pace_overdue():
    pace = compute_pace(goal(target=300), current=100, today=date(2026, 11, 1))
    assert (pace.state, pace.remaining, pace.days_left, pace.per_day) == ("overdue", 200, 0, 0)


def test_pace_chapter_goal():
    pace = compute_pace(goal(target=12, unit="chapters", deadline="2026-10-12"), current=0, today=date(2026, 10, 1))
    assert (pace.remaining, pace.days_left, pace.per_day) == (12, 12, 1)


def test_not_behind_on_the_first_day():
    assert compute_pace(goal(), current=0, today=date(2026, 10, 1)).behind is False


def test_behind_and_on_track():
    # Nach 10 von 31 Tagen wären gleichmäßig rund 322 Seiten gelesen.
    today = date(2026, 10, 11)
    assert compute_pace(goal(), current=100, today=today).behind is True
    assert compute_pace(goal(), current=322, today=today).behind is False
    assert compute_pace(goal(), current=600, today=today).behind is False


def test_behind_counts_from_where_the_goal_started():
    started_late = goal(start_value=500, start_date="2026-10-21")
    assert compute_pace(started_late, current=500, today=date(2026, 10, 21)).behind is False
    assert compute_pace(started_late, current=500, today=date(2026, 10, 26)).behind is True


def test_describe_pace_speaks_german_and_names_the_amount():
    text = describe_pace(goal(), compute_pace(goal(), 0, date(2026, 10, 1)))
    assert "33 Seiten am Tag" in text and "31.10.2026" in text
    one = goal(target=1, unit="chapters", deadline="2026-10-01")
    assert "1 Kapitel am Tag" in describe_pace(one, compute_pace(one, 0, date(2026, 10, 1)))


# ── Wann eine Erinnerung rausgehen darf ───────────────────────────────────────

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
TODAY = date(2026, 10, 11)


def reminder(interval_days=7, last_sent_at=None):
    return {"interval_days": interval_days, "last_sent_at": last_sent_at}


def test_due_when_behind_and_never_sent():
    assert reminder_is_due(reminder(), goal(), 100, NOW, TODAY) is True


def test_not_due_when_on_track():
    assert reminder_is_due(reminder(), goal(), 600, NOW, TODAY) is False


def test_not_due_when_goal_reached():
    assert reminder_is_due(reminder(), goal(target=300), 300, NOW, TODAY) is False


def test_not_due_after_the_deadline():
    late = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)
    assert reminder_is_due(reminder(), goal(), 100, late, date(2026, 11, 2)) is False


def test_not_due_without_goal_or_readable_progress():
    assert reminder_is_due(reminder(), None, 100, NOW, TODAY) is False
    assert reminder_is_due(reminder(), goal(), None, NOW, TODAY) is False


def test_interval_is_respected():
    six_days_ago = (NOW - timedelta(days=6)).isoformat()
    seven_days_ago = (NOW - timedelta(days=7)).isoformat()
    assert reminder_is_due(reminder(7, six_days_ago), goal(), 100, NOW, TODAY) is False
    assert reminder_is_due(reminder(7, seven_days_ago), goal(), 100, NOW, TODAY) is True
    assert reminder_is_due(reminder(1, six_days_ago), goal(), 100, NOW, TODAY) is True


# ── Datenbank und Versand ─────────────────────────────────────────────────────

@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.setup()
    await database.set_book(ISBN, "Der Schwarm", None, None, None, 1000, 1)
    yield database
    await database.close()


async def add_member(db, user_id, pages, with_reminder):
    await db.update_progress(user_id, GUILD, ISBN, "pages", pages)
    await db.set_goal(user_id, GUILD, ISBN, "pages", 1000, "2026-10-31", 0, "2026-10-01")
    if with_reminder:
        await db.enable_reminder(user_id, GUILD, ISBN, 7)


class Outbox:
    def __init__(self, closed_for=()):
        self.messages = []
        self.closed_for = set(closed_for)

    async def send(self, user_id, text):
        if user_id in self.closed_for:
            raise discord.Forbidden(type("Response", (), {"status": 403, "reason": "Forbidden"})(), "closed")
        self.messages.append((user_id, text))


async def test_goal_alone_never_creates_a_reminder(db):
    await add_member(db, 1, pages=100, with_reminder=False)
    assert await db.get_reminder(1, GUILD, ISBN) is None
    assert await db.get_reminders(ISBN) == []

    outbox = Outbox()
    assert await send_due_reminders(db, outbox.send, NOW, TODAY) == 0
    assert outbox.messages == []


async def test_only_members_who_switched_it_on_get_a_message(db):
    await add_member(db, 1, pages=100, with_reminder=True)
    await add_member(db, 2, pages=100, with_reminder=False)

    outbox = Outbox()
    assert await send_due_reminders(db, outbox.send, NOW, TODAY) == 1
    assert [user for user, _ in outbox.messages] == [1]
    assert "/erinnerung aus" in outbox.messages[0][1]


async def test_no_second_message_inside_the_interval(db):
    await add_member(db, 1, pages=100, with_reminder=True)
    outbox = Outbox()
    await send_due_reminders(db, outbox.send, NOW, TODAY)
    later = NOW + timedelta(days=3)
    assert await send_due_reminders(db, outbox.send, later, later.date()) == 0
    assert len(outbox.messages) == 1


async def test_switching_off_stops_messages(db):
    await add_member(db, 1, pages=100, with_reminder=True)
    assert await db.disable_reminder(1, GUILD, ISBN) is True
    outbox = Outbox()
    assert await send_due_reminders(db, outbox.send, NOW, TODAY) == 0


async def test_deleting_the_goal_removes_the_reminder(db):
    await add_member(db, 1, pages=100, with_reminder=True)
    assert await db.delete_goal(1, GUILD, ISBN) is True
    assert await db.get_reminder(1, GUILD, ISBN) is None


async def test_changing_the_goal_keeps_the_reminder(db):
    await add_member(db, 1, pages=100, with_reminder=True)
    await db.set_goal(1, GUILD, ISBN, "pages", 500, "2026-11-30", 100, "2026-10-11")
    assert (await db.get_reminder(1, GUILD, ISBN))["interval_days"] == 7
    assert (await db.get_goal(1, GUILD, ISBN))["target"] == 500


async def test_closed_direct_messages_do_not_stop_the_others(db):
    await add_member(db, 1, pages=100, with_reminder=True)
    await add_member(db, 2, pages=100, with_reminder=True)

    outbox = Outbox(closed_for={1})
    assert await send_due_reminders(db, outbox.send, NOW, TODAY) == 1
    assert [user for user, _ in outbox.messages] == [2]
    # Auch der abgewiesene Versuch zählt, sonst klopft der Bot jede Stunde neu an.
    assert (await db.get_reminder(1, GUILD, ISBN))["last_sent_at"] is not None


async def test_no_message_without_a_current_book():
    database = Database(":memory:")
    await database.setup()
    outbox = Outbox()
    assert await send_due_reminders(database, outbox.send, NOW, TODAY) == 0
    await database.close()


def test_parse_date_accepts_both_forms():
    assert parse_date("31.10.2026") == date(2026, 10, 31)
    assert parse_date(" 2026-10-31 ") == date(2026, 10, 31)
    assert parse_date("morgen") is None
    assert parse_date("31.02.2026") is None


# ── Wann ein Buch als abgeschlossen gilt ──────────────────────────────────────

def test_is_complete():
    assert is_complete("percent", 100, None, None, None, None) is True
    assert is_complete("percent", 99, None, None, None, None) is False
    assert is_complete("pages", 352, None, None, 352, 18) is True
    assert is_complete("pages", 351, None, None, 352, 18) is False
    assert is_complete("chapters", 18, None, None, 352, 18) is True
    assert is_complete("chapters", 17, None, None, 352, 18) is False
    assert is_complete("chapters", 11, "percent", 100, None, None) is True
    assert is_complete("chapters", 11, "pages", 352, 352, 18) is True


def test_nothing_is_complete_without_a_known_total():
    assert is_complete("pages", 9999, None, None, None, None) is False
    assert is_complete("chapters", 99, None, None, None, None) is False


async def test_profile_counts_only_finished_books(db):
    await db.update_progress(1, GUILD, ISBN, "percent", 100, completed=True)
    await db.update_progress(2, GUILD, ISBN, "percent", 46)
    await db.set_book("9783492954525", "Das nächste Buch", None, None, None, None, 1)

    assert (await db.get_user_profile(1, GUILD))["books_completed"] == 1
    assert (await db.get_user_profile(1, GUILD))["last_isbn"] == ISBN
    assert (await db.get_user_profile(2, GUILD))["books_completed"] == 0
    assert (await db.get_user_profile(2, GUILD))["last_isbn"] is None


async def test_finished_current_book_counts_right_away(db):
    await db.update_progress(1, GUILD, ISBN, "pages", 1000, completed=True)
    assert (await db.get_user_profile(1, GUILD))["books_completed"] == 1


async def test_first_completion_date_stays_and_a_correction_clears_it(db):
    await db.update_progress(1, GUILD, ISBN, "percent", 100, completed=True)
    await db._conn.execute("UPDATE reading_progress SET completed_at = '2026-05-09 10:00:00'")
    await db.update_progress(1, GUILD, ISBN, "percent", 100, completed=True)
    assert (await db.get_progress(1, GUILD, ISBN))["completed_at"] == "2026-05-09 10:00:00"

    await db.update_progress(1, GUILD, ISBN, "percent", 80)
    assert (await db.get_progress(1, GUILD, ISBN))["completed_at"] is None
