"""
Tests für Achievements und Ränge

Die Regeln sind reine Funktionen und werden direkt geprüft; die Datenbankseite
läuft gegen SQLite im Speicher, Discord ist durch eine Attrappe ersetzt.
"""

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import re

import discord

from cogs.achievements import (
    SHARE_PATTERN, ShareButton, after_progress, check_member, share_achievement, should_count, show_unseen, unlock_messages,
    valid_achievement,
)
from database import Database
from services.achievements import (
    BY_KEY, CATALOGUE, RANK_KEY, badge_specs, earned, event_unlocks, next_rank, overview, rank_for, share_text, unlock_title,
)

ROOT = Path(__file__).resolve().parent.parent
GUILD = 999
BOOK1 = "9783328103349"
BOOK2 = "9783492954525"
UTC = timezone.utc


def stats(**values):
    base = {k: 0 for k in ("books_finished", "fortschritt_count", "goals_reached_early", "thread_messages",
                           "pages_read", "first_finishes", "all_finished_books")}
    return {**base, **values}


# ── Katalog und Stufen ────────────────────────────────────────────────────────

def test_tier_boundaries():
    assert ("fleissig", 1) not in earned(stats(fortschritt_count=9))
    assert ("fleissig", 1) in earned(stats(fortschritt_count=10))
    assert {("letzte_seite", 1), ("letzte_seite", 2)} <= earned(stats(books_finished=3))
    assert ("letzte_seite", 3) not in earned(stats(books_finished=3))
    assert ("seitenfresser", 1) in earned(stats(pages_read=500))
    assert ("seitenfresser", 1) not in earned(stats(pages_read=499))


def test_single_and_secret_conditions():
    assert ("gascogne", 0) in earned(stats(fortschritt_count=1))
    assert ("schnellster_degen", 0) in earned(stats(first_finishes=1))
    assert ("einer_fuer_alle", 0) in earned(stats(all_finished_books=1))
    assert ("diamantspangen", 0) not in earned(stats(books_finished=11))
    assert ("diamantspangen", 0) in earned(stats(books_finished=12))
    assert earned(stats()) == set()


def test_ranks_follow_dartagnan():
    assert rank_for(0)[0] == "Gascogner"
    assert rank_for(1)[0] == "Gardist bei des Essarts"
    assert rank_for(3)[0] == "Buchketier"
    assert rank_for(25)[0] == "Marschall von Frankreich"
    assert next_rank(1) == ("Buchketier", 2)
    assert next_rank(20) is None
    assert {(RANK_KEY, 1), (RANK_KEY, 2)} <= earned(stats(books_finished=3))
    assert unlock_title(RANK_KEY, 2) == "Beförderung: Buchketier"


def test_wooden_book_is_the_first_trophy():
    assert unlock_title("letzte_seite", 1) == "Bis zur letzten Seite · Das hölzerne Buch"
    assert unlock_title("seitenfresser", 1) == "Seitenfresser · Leseraupe"
    assert unlock_title("fleissig", 4) == "Fleißiges Buchketier · Gold"


# ── Ereignisse ────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
BOOK = {"total_pages": 400, "total_chapters": 20}


def at(hour, minute=0):
    return datetime(2026, 10, 1, hour, minute)


def test_night_ride_between_midnight_and_four():
    new = {"mode": "pages", "current": 10}
    assert "naechtlicher_ausritt" in event_unlocks(None, new, BOOK, at(0, 0), NOW, True)
    assert "naechtlicher_ausritt" in event_unlocks(None, new, BOOK, at(3, 59), NOW, True)
    assert "naechtlicher_ausritt" not in event_unlocks(None, new, BOOK, at(4, 0), NOW, True)
    assert "naechtlicher_ausritt" not in event_unlocks(None, new, BOOK, at(23, 59), NOW, True)


def test_freibrief_only_outside_the_club_books():
    new = {"mode": "pages", "current": 10}
    assert "freibrief" in event_unlocks(None, new, None, at(12), NOW, is_club_book=False)
    assert "freibrief" not in event_unlocks(None, new, BOOK, at(12), NOW, is_club_book=True)


def test_gewaltritt_needs_a_quarter_within_a_day():
    earlier = (NOW - timedelta(hours=20)).strftime("%Y-%m-%d %H:%M:%S")
    too_early = (NOW - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
    before = {"mode": "pages", "current": 100, "updated_at": earlier}
    assert "gewaltritt" in event_unlocks(before, {"mode": "pages", "current": 200}, BOOK, at(12), NOW, True)
    assert "gewaltritt" not in event_unlocks(before, {"mode": "pages", "current": 199}, BOOK, at(12), NOW, True)
    late = {**before, "updated_at": too_early}
    assert "gewaltritt" not in event_unlocks(late, {"mode": "pages", "current": 300}, BOOK, at(12), NOW, True)
    percent = {"mode": "percent", "current": 40, "updated_at": earlier}
    assert "gewaltritt" in event_unlocks(percent, {"mode": "percent", "current": 65}, None, at(12), NOW, True)


# ── Übersicht ─────────────────────────────────────────────────────────────────

def test_secret_ones_stay_hidden_until_unlocked():
    lines = dict(overview(stats(), set()))
    assert "▫️ ???" in lines
    assert not any("Diamantspangen" in title for title in lines)
    unlocked = dict(overview(stats(books_finished=12), {("diamantspangen", 0)}))
    assert "🏅 Die zwölf Diamantspangen" in unlocked


def test_overview_shows_the_way_to_the_next_tier():
    lines = dict(overview(stats(fortschritt_count=12), {("fleissig", 1)}))
    assert lines["🏅 Fleißiges Buchketier · Holz"] == "12 von 50 bis Bronze"
    assert lines["▫️ Bis zur letzten Seite"] == "0 von 1 bis Das hölzerne Buch"
    assert lines["▫️ Nächtlicher Ausritt"].startswith("Trag deinen Fortschritt")


def test_every_badge_exists():
    missing = [spec["file"] for spec in badge_specs() if not (ROOT / "assets" / "badges" / spec["file"]).exists()]
    assert missing == []
    assert len(badge_specs()) == 5 * 4 + 7 + 1


def test_unlock_messages_split_at_ten_and_share_badges():
    unlocks = [("fleissig", 1)] * 3 + [(a.key, 0) for a in CATALOGUE if a.kind != "tiered"] + [("letzte_seite", t) for t in (1, 2, 3, 4)]
    messages = unlock_messages(unlocks, stats(fortschritt_count=10))
    assert [len(embeds) for embeds, _ in messages] == [10, 4]
    first_files = [f.filename for f in messages[0][1]]
    assert first_files.count("fleissig-holz.png") == 1
    assert all(e.footer.text is None or "Nur du siehst das" in e.footer.text for embeds, _ in messages for e in embeds)


# ── Datenbank ─────────────────────────────────────────────────────────────────

@pytest.fixture
async def db():
    database = Database(":memory:")
    await database.setup()
    await database.set_book(BOOK1, "Prinzessin Insomnia", None, None, None, 352, 0)
    yield database
    await database.close()


async def test_book_list_keeps_thread_and_chapters(db):
    assert await db.set_book_thread(BOOK1, 111) is True
    await db.set_total_chapters(18)
    await db.set_book(BOOK1, "Prinzessin Insomnia", None, None, None, 352, 0)
    record = await db.get_book_record(BOOK1)
    assert (record["thread_id"], record["total_chapters"], record["total_pages"]) == (111, 18, 352)
    assert await db.book_thread_ids() == {111}


async def test_stats_from_the_club_history(db):
    await db.update_progress(1, GUILD, BOOK1, "percent", 100, completed=True)
    await db._conn.execute("UPDATE reading_progress SET completed_at = '2026-05-09 17:56:13' WHERE user_id = 1")
    await db.update_progress(2, GUILD, BOOK1, "percent", 100, completed=True)
    await db._conn.execute("UPDATE reading_progress SET completed_at = '2026-05-28 15:11:09' WHERE user_id = 2")
    await db.update_progress(3, GUILD, BOOK1, "percent", 46)
    await db.set_book(BOOK2, "Das Erste Horn", None, None, None, 397, 0)
    await db.update_progress(1, GUILD, BOOK2, "pages", 100)

    first = await db.achievement_stats(1, GUILD)
    assert (first["books_finished"], first["first_finishes"], first["all_finished_books"]) == (1, 1, 0)
    assert first["pages_read"] == 352 + 100
    second = await db.achievement_stats(2, GUILD)
    assert (second["first_finishes"], second["pages_read"]) == (0, 352)
    assert (await db.achievement_stats(3, GUILD))["pages_read"] == round(352 * 0.46)

    await db.update_progress(3, GUILD, BOOK1, "percent", 100, completed=True)
    assert (await db.achievement_stats(2, GUILD))["all_finished_books"] == 1


async def test_einer_fuer_alle_needs_two_readers(db):
    await db.update_progress(1, GUILD, BOOK1, "percent", 100, completed=True)
    assert (await db.achievement_stats(1, GUILD))["all_finished_books"] == 0


async def test_goals_reached_early_count_and_late_do_not(db):
    assert await db.record_goal_reached(1, GUILD, BOOK1, 352, "2026-10-31", "2026-10-20") is True
    assert await db.record_goal_reached(1, GUILD, BOOK1, 352, "2026-10-31", "2026-10-21") is False  # dasselbe Ziel
    await db.record_goal_reached(1, GUILD, BOOK1, 100, "2026-09-01", "2026-09-05")  # zu spät
    assert (await db.achievement_stats(1, GUILD))["goals_reached_early"] == 1


async def test_check_is_idempotent_and_tracks_seen(db):
    for _ in range(10):
        await db.increment_fortschritt_count(1, GUILD)
    first = await check_member(db, 1, GUILD)
    assert first == [("fleissig", 1), ("gascogne", 0)]
    assert await check_member(db, 1, GUILD) == []
    assert await db.get_unseen(1, GUILD) == [("fleissig", 1), ("gascogne", 0)]
    await db.mark_seen(1, GUILD)
    assert await db.get_unseen(1, GUILD) == []


async def test_thread_messages_count(db):
    await db.add_thread_message(1, GUILD)
    await db.add_thread_message(1, GUILD, count=24)
    assert ("plaudertasche", 1) in await check_member(db, 1, GUILD)


def test_should_count_only_people_in_book_threads():
    assert should_count(111, False, {111, 222}) is True
    assert should_count(111, True, {111}) is False
    assert should_count(333, False, {111}) is False


# ── Ablauf nach /fortschritt ──────────────────────────────────────────────────

class Followup:
    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append({"content": content, **kwargs})


def interaction_for(user_id):
    return SimpleNamespace(user=SimpleNamespace(id=user_id), guild_id=GUILD, followup=Followup())


async def test_after_progress_records_goal_and_answers_privately(db):
    bot = SimpleNamespace(db=db)
    book = await db.get_book()
    await db.set_goal(1, GUILD, BOOK1, "pages", 100, "2099-12-31", 0, "2026-01-01")
    await db.update_progress(1, GUILD, BOOK1, "pages", 120)
    await db.increment_fortschritt_count(1, GUILD)

    interaction = interaction_for(1)
    await after_progress(bot, interaction, None, BOOK1, book, completed=False)

    unlocked = await db.get_achievements(1, GUILD)
    assert {("gascogne", 0), ("streber", 1)} <= unlocked
    assert interaction.followup.sent and all(m["ephemeral"] is True for m in interaction.followup.sent)
    assert await db.get_unseen(1, GUILD) == []


async def test_finishing_a_book_checks_the_other_readers_silently(db):
    bot = SimpleNamespace(db=db)
    book = await db.get_book()
    await db.update_progress(2, GUILD, BOOK1, "percent", 100, completed=True)
    await db.update_progress(1, GUILD, BOOK1, "percent", 100, completed=True)

    interaction = interaction_for(1)
    await after_progress(bot, interaction, None, BOOK1, book, completed=True)

    assert ("einer_fuer_alle", 0) in await db.get_achievements(2, GUILD)
    assert ("einer_fuer_alle", 0) in await db.get_unseen(2, GUILD)  # sieht es erst beim nächsten eigenen Befehl


async def test_after_progress_never_breaks_the_entry(db):
    class Broken:
        async def get_progress(self, *args):
            raise RuntimeError("kaputt")

    await after_progress(SimpleNamespace(db=Broken()), interaction_for(1), None, BOOK1, None, completed=False)


# ── Privatsphäre ──────────────────────────────────────────────────────────────

def test_only_sharing_goes_public():
    """Jeder Sendeaufruf ist ephemeral, mit genau einer Ausnahme: der Post in share_achievement."""
    tree = ast.parse((ROOT / "cogs" / "achievements.py").read_text())
    private, public = [], []
    for function in ast.walk(tree):
        if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in ("send", "send_message", "defer"):
                owner = ast.unparse(node.func.value)
                ephemeral = any(k.arg == "ephemeral" and getattr(k.value, "value", None) is True for k in node.keywords)
                (private if ephemeral else public).append((function.name, owner))
                if ephemeral:
                    assert owner.startswith("interaction"), (function.name, owner)
    assert private
    assert public == [("share_achievement", "channel")], public


# ── Teilen ────────────────────────────────────────────────────────────────────

class Channel:
    def __init__(self, fail=False):
        self.posts, self.fail, self.mention = [], fail, "#002"

    async def send(self, **kwargs):
        if self.fail:
            raise discord.HTTPException(SimpleNamespace(status=500, reason="kaputt"), "kaputt")
        self.posts.append(kwargs)


class Response:
    def __init__(self):
        self.deferred = []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)


def share_setup(db, channel):
    bot = SimpleNamespace(db=db, get_channel=lambda _id: channel)
    interaction = SimpleNamespace(
        user=SimpleNamespace(id=1, mention="<@1>"), guild_id=GUILD, channel=channel,
        response=Response(), followup=Followup(),
    )
    return bot, interaction


async def test_share_posts_once_in_the_book_thread(db):
    await db.set_book_thread(BOOK1, 111)
    await db.store_achievements(1, GUILD, {("letzte_seite", 1)})
    thread = Channel()
    bot, interaction = share_setup(db, thread)

    assert await share_achievement(bot, interaction, "letzte_seite", 1) is True
    assert len(thread.posts) == 1
    post = thread.posts[0]
    assert "hölzerne Buch" in post["embed"].title and "<@1>" in post["embed"].description
    assert post["allowed_mentions"].users is False
    assert all(m["ephemeral"] for m in interaction.followup.sent)

    assert await share_achievement(bot, interaction, "letzte_seite", 1) is False
    assert len(thread.posts) == 1
    assert interaction.followup.sent[-1]["content"] == "Das hast du schon geteilt."


async def test_nobody_shares_what_they_do_not_have(db):
    thread = Channel()
    bot, interaction = share_setup(db, thread)
    assert await share_achievement(bot, interaction, "diamantspangen", 0) is False
    assert await share_achievement(bot, interaction, "gibt_es_nicht", 0) is False
    assert thread.posts == []
    assert [m["content"] for m in interaction.followup.sent] == ["Dieses Achievement hast du (noch) nicht."] * 2


async def test_failed_post_can_be_shared_again(db):
    await db.store_achievements(1, GUILD, {("gascogne", 0)})
    bot, interaction = share_setup(db, Channel(fail=True))
    assert await share_achievement(bot, interaction, "gascogne", 0) is False
    assert await db.get_unshared(1, GUILD) == [("gascogne", 0)]


async def test_unseen_notes_carry_one_share_button_each(db):
    await db.store_achievements(1, GUILD, {("gascogne", 0), ("letzte_seite", 1)})
    interaction = interaction_for(1)
    assert await show_unseen(interaction, db) == 2
    view = interaction.followup.sent[0]["view"]
    assert sorted(item.custom_id for item in view.children) == ["buchketiere:teilen:gascogne:0", "buchketiere:teilen:letzte_seite:1"]


async def test_share_button_survives_a_restart():
    button = ShareButton("letzte_seite", 1)
    match = re.fullmatch(SHARE_PATTERN, button.item.custom_id)
    rebuilt = await ShareButton.from_custom_id(None, None, match)
    assert (rebuilt.key, rebuilt.tier) == ("letzte_seite", 1)
    assert len(button.item.label) <= 80


def test_share_text_names_the_shared_tier():
    assert share_text("letzte_seite", 1, stats(books_finished=3), "<@1>").startswith("<@1> hat 1 Buch bis zur letzten Seite")
    assert share_text(RANK_KEY, 1, stats(), "<@1>") == "<@1> wurde befördert: **Gardist bei des Essarts**. Noch kein Buchketier, aber schon in Uniform."
    assert all(a.shared for a in CATALOGUE)


def test_valid_achievement():
    assert valid_achievement("letzte_seite", 4) and not valid_achievement("letzte_seite", 5)
    assert valid_achievement("gascogne", 0) and not valid_achievement("gascogne", 1)
    assert valid_achievement(RANK_KEY, 5) and not valid_achievement(RANK_KEY, 6)
    assert not valid_achievement("gibt_es_nicht", 0)
