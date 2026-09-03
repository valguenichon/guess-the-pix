import asyncio
import sqlite3
import tempfile
from pathlib import Path

from database import Database


V0_SCHEMA = """
CREATE TABLE guild_state (
    guild_id INTEGER PRIMARY KEY,
    current_master_id INTEGER,
    previous_master_id INTEGER,
    current_period_id INTEGER,
    period_round_limit INTEGER,
    default_attempt_limit INTEGER,
    scoreboard_channel_id INTEGER,
    scoreboard_message_id INTEGER
);
CREATE TABLE periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    number INTEGER NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    round_limit INTEGER,
    round_count_offset INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    UNIQUE(guild_id, number)
);
CREATE TABLE participants (
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    joined_at TEXT NOT NULL,
    PRIMARY KEY (guild_id, user_id)
);
CREATE TABLE rounds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    channel_id INTEGER NOT NULL,
    master_id INTEGER NOT NULL,
    period_id INTEGER,
    attempt_limit INTEGER,
    solution TEXT NOT NULL,
    image_url TEXT,
    round_message_id INTEGER,
    hint_1 TEXT,
    hint_2 TEXT,
    hint_3 TEXT,
    hint_1_revealed_at TEXT,
    hint_2_revealed_at TEXT,
    hint_3_revealed_at TEXT,
    hint_1_scheduled_at TEXT,
    hint_2_scheduled_at TEXT,
    hint_3_scheduled_at TEXT,
    accelerated_at TEXT,
    original_ends_at TEXT,
    started_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    closed_at TEXT,
    status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    round_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    answer TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    reviewed_at TEXT,
    reviewed_by INTEGER,
    result_notified_at TEXT,
    final_rank INTEGER,
    awarded_points INTEGER,
    FOREIGN KEY(round_id) REFERENCES rounds(id)
);
CREATE TABLE score_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    round_id INTEGER,
    period_id INTEGER,
    points INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(round_id) REFERENCES rounds(id)
);
"""


def seed_v0133(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(V0_SCHEMA)
    con.execute(
        "INSERT INTO guild_state VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (100, 11, 22, 1, 10, 3, 1001, 9999),
    )
    con.execute(
        "INSERT INTO periods(guild_id, number, started_at, round_limit, status) VALUES (100, 1, '2026-08-01T00:00:00+00:00', 10, 'active')"
    )
    con.execute(
        "INSERT INTO participants VALUES (100, 11, 1, '2026-08-01T00:00:00+00:00')"
    )
    con.execute(
        """INSERT INTO rounds(
            guild_id, channel_id, master_id, period_id, attempt_limit,
            solution, image_url, hint_1, hint_2, hint_3,
            started_at, ends_at, closed_at, status
        ) VALUES (100, 1001, 11, 1, 3, 'Game A', 'https://example.invalid/a.png',
                  'h1', 'h2', 'h3', '2026-08-01T00:00:00+00:00',
                  '2026-08-08T00:00:00+00:00', '2026-08-08T00:00:00+00:00', 'closed')"""
    )
    con.execute(
        """INSERT INTO rounds(
            guild_id, channel_id, master_id, period_id, attempt_limit,
            solution, image_url, hint_1, hint_2, hint_3,
            started_at, ends_at, status
        ) VALUES (100, 1001, 22, 1, 3, 'Game B', 'https://example.invalid/b.png',
                  'h1', 'h2', 'h3', '2026-08-09T00:00:00+00:00',
                  '2026-08-16T00:00:00+00:00', 'open')"""
    )
    con.execute(
        "INSERT INTO attempts(guild_id, round_id, user_id, answer, submitted_at, status) VALUES (100, 2, 11, 'guess', '2026-08-10T00:00:00+00:00', 'pending')"
    )
    con.execute(
        "INSERT INTO score_events(guild_id, user_id, round_id, period_id, points, reason, created_at) VALUES (100, 11, 1, 1, 6, 'test', '2026-08-08T00:00:00+00:00')"
    )
    con.commit()
    con.close()


async def scenario(path: Path) -> None:
    db = Database(path)
    await db.init()

    # Configuration mono-serveur issue du .env v0.13.3.
    assert await db.migrate_legacy_config(100, 1001, 2001) is True

    config = await db.get_guild_config(100)
    assert config is not None
    assert config["game_channel_id"] == 1001
    assert config["admin_role_id"] == 2001
    assert (await db.get_guild_registration(100))["status"] == "configured"

    rounds = [await db.get_round(1), await db.get_round(2)]
    assert [row["round_number"] for row in rounds] == [1, 2]
    assert [row["solution"] for row in rounds] == ["Game A", "Game B"]
    assert (await db.active_participant_ids(100)) == [11]
    assert (await db.leaderboard(100))[0]["score"] == 6
    assert (await db.get_state(100))["current_master_id"] == 11

    # Second init + second tentative de migration : aucune duplication ni renumérotation.
    await db.init()
    assert await db.migrate_legacy_config(100, 1001, 2001) is False
    rounds_after = [await db.get_round(1), await db.get_round(2)]
    assert [row["round_number"] for row in rounds_after] == [1, 2]
    assert (await db.active_participant_ids(100)) == [11]
    assert (await db.leaderboard(100))[0]["score"] == 6


def test_v0133_migration_is_idempotent():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "scoreboard.db"
        seed_v0133(path)
        asyncio.run(scenario(path))
