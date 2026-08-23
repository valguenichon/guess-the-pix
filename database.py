from __future__ import annotations

import random
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

import aiosqlite


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: Path):
        self.path = path

    @asynccontextmanager
    async def connection(self):
        db = await aiosqlite.connect(self.path)
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        try:
            yield db
        finally:
            await db.close()

    async def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        async with self.connection() as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS guild_state (
                    guild_id INTEGER PRIMARY KEY,
                    current_master_id INTEGER,
                    previous_master_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS participants (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    joined_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id)
                );

                CREATE TABLE IF NOT EXISTS rounds (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    master_id INTEGER NOT NULL,
                    solution TEXT NOT NULL,
                    image_url TEXT,
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

                CREATE INDEX IF NOT EXISTS idx_rounds_open
                    ON rounds(guild_id, status, ends_at);

                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    round_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    answer TEXT NOT NULL,
                    submitted_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    reviewed_at TEXT,
                    reviewed_by INTEGER,
                    FOREIGN KEY(round_id) REFERENCES rounds(id)
                );

                CREATE INDEX IF NOT EXISTS idx_attempts_round
                    ON attempts(round_id, status, submitted_at);

                CREATE TABLE IF NOT EXISTS score_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    round_id INTEGER,
                    points INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(round_id) REFERENCES rounds(id)
                );
                """
            )

            # Migrations légères pour les installations existantes.
            columns = {row["name"] for row in await (await db.execute("PRAGMA table_info(guild_state)")).fetchall()}
            if "scoreboard_channel_id" not in columns:
                await db.execute("ALTER TABLE guild_state ADD COLUMN scoreboard_channel_id INTEGER")
            if "scoreboard_message_id" not in columns:
                await db.execute("ALTER TABLE guild_state ADD COLUMN scoreboard_message_id INTEGER")

            round_columns = {row["name"] for row in await (await db.execute("PRAGMA table_info(rounds)")).fetchall()}
            for column, definition in (
                ("hint_1", "TEXT"),
                ("hint_2", "TEXT"),
                ("hint_3", "TEXT"),
                ("hint_1_revealed_at", "TEXT"),
                ("hint_2_revealed_at", "TEXT"),
                ("hint_3_revealed_at", "TEXT"),
                ("hint_1_scheduled_at", "TEXT"),
                ("hint_2_scheduled_at", "TEXT"),
                ("hint_3_scheduled_at", "TEXT"),
                ("accelerated_at", "TEXT"),
                ("original_ends_at", "TEXT"),
            ):
                if column not in round_columns:
                    await db.execute(f"ALTER TABLE rounds ADD COLUMN {column} {definition}")

            # Initialise les nouveaux horaires sur les manches déjà présentes.
            # Pour les anciennes manches, ends_at correspond à la limite historique J+7.
            existing_rounds = await (await db.execute(
                """
                SELECT id, started_at, ends_at, original_ends_at,
                       hint_1_scheduled_at, hint_2_scheduled_at, hint_3_scheduled_at
                FROM rounds
                """
            )).fetchall()
            for row in existing_rounds:
                started = datetime.fromisoformat(row["started_at"])
                original_ends_at = row["original_ends_at"] or row["ends_at"]
                hint_1_at = row["hint_1_scheduled_at"] or (started + timedelta(days=2)).isoformat()
                hint_2_at = row["hint_2_scheduled_at"] or (started + timedelta(days=4)).isoformat()
                hint_3_at = row["hint_3_scheduled_at"] or (started + timedelta(days=6)).isoformat()
                await db.execute(
                    """
                    UPDATE rounds
                    SET original_ends_at = ?,
                        hint_1_scheduled_at = ?, hint_2_scheduled_at = ?, hint_3_scheduled_at = ?
                    WHERE id = ?
                    """,
                    (original_ends_at, hint_1_at, hint_2_at, hint_3_at, row["id"]),
                )

            await db.commit()

    async def ensure_guild(self, guild_id: int) -> None:
        async with self.connection() as db:
            await db.execute(
                "INSERT OR IGNORE INTO guild_state(guild_id) VALUES (?)", (guild_id,)
            )
            await db.commit()

    async def set_master(self, guild_id: int, user_id: int, previous_master_id: int | None = None) -> None:
        await self.ensure_guild(guild_id)
        async with self.connection() as db:
            if previous_master_id is None:
                row = await (await db.execute(
                    "SELECT current_master_id FROM guild_state WHERE guild_id = ?", (guild_id,)
                )).fetchone()
                previous_master_id = row["current_master_id"] if row else None
            await db.execute(
                """
                UPDATE guild_state
                SET previous_master_id = ?, current_master_id = ?
                WHERE guild_id = ?
                """,
                (previous_master_id, user_id, guild_id),
            )
            await db.commit()

    async def clear_master(self, guild_id: int, previous_master_id: int | None = None) -> None:
        await self.ensure_guild(guild_id)
        async with self.connection() as db:
            await db.execute(
                """
                UPDATE guild_state
                SET previous_master_id = ?, current_master_id = NULL
                WHERE guild_id = ?
                """,
                (previous_master_id, guild_id),
            )
            await db.commit()

    async def get_state(self, guild_id: int):
        await self.ensure_guild(guild_id)
        async with self.connection() as db:
            return await (await db.execute(
                "SELECT * FROM guild_state WHERE guild_id = ?", (guild_id,)
            )).fetchone()

    async def set_scoreboard_message(self, guild_id: int, channel_id: int, message_id: int) -> None:
        await self.ensure_guild(guild_id)
        async with self.connection() as db:
            await db.execute(
                """
                UPDATE guild_state
                SET scoreboard_channel_id = ?, scoreboard_message_id = ?
                WHERE guild_id = ?
                """,
                (channel_id, message_id, guild_id),
            )
            await db.commit()

    async def clear_scoreboard_message(self, guild_id: int) -> None:
        await self.ensure_guild(guild_id)
        async with self.connection() as db:
            await db.execute(
                """
                UPDATE guild_state
                SET scoreboard_channel_id = NULL, scoreboard_message_id = NULL
                WHERE guild_id = ?
                """,
                (guild_id,),
            )
            await db.commit()

    async def reset_guild(self, guild_id: int) -> None:
        """Remet entièrement à zéro les données de jeu de ce serveur.

        Le message de scoreboard permanent est conservé afin de pouvoir être
        actualisé immédiatement après la remise à zéro.
        """
        await self.ensure_guild(guild_id)
        async with self.connection() as db:
            await db.execute("BEGIN")
            await db.execute("DELETE FROM attempts WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM score_events WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM rounds WHERE guild_id = ?", (guild_id,))
            await db.execute("DELETE FROM participants WHERE guild_id = ?", (guild_id,))
            await db.execute(
                """
                UPDATE guild_state
                SET current_master_id = NULL, previous_master_id = NULL
                WHERE guild_id = ?
                """,
                (guild_id,),
            )

            # Si ces tables sont désormais totalement vides, on remet aussi
            # leurs compteurs AUTOINCREMENT à zéro : la prochaine manche
            # recommencera alors à #1. Ce test évite d'affecter un autre serveur
            # dans l'hypothèse où le bot serait un jour réutilisé ailleurs.
            for table in ("rounds", "attempts", "score_events"):
                row = await (await db.execute(f"SELECT COUNT(*) AS n FROM {table}")).fetchone()
                if int(row["n"]) == 0:
                    await db.execute("DELETE FROM sqlite_sequence WHERE name = ?", (table,))

            await db.commit()

    async def round_participant_count(self, round_id: int) -> int:
        async with self.connection() as db:
            row = await (await db.execute(
                "SELECT COUNT(DISTINCT user_id) AS n FROM attempts WHERE round_id = ?",
                (round_id,),
            )).fetchone()
            return int(row["n"])

    async def set_participant(self, guild_id: int, user_id: int, active: bool) -> None:
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO participants(guild_id, user_id, active, joined_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id)
                DO UPDATE SET active = excluded.active
                """,
                (guild_id, user_id, 1 if active else 0, utcnow_iso()),
            )
            await db.commit()

    async def random_participant(self, guild_id: int, excluded: Iterable[int]) -> int | None:
        excluded = set(excluded)
        async with self.connection() as db:
            rows = await (await db.execute(
                "SELECT user_id FROM participants WHERE guild_id = ? AND active = 1",
                (guild_id,),
            )).fetchall()
        choices = [row["user_id"] for row in rows if row["user_id"] not in excluded]
        return random.choice(choices) if choices else None

    async def is_participant_active(self, guild_id: int, user_id: int) -> bool:
        async with self.connection() as db:
            row = await (await db.execute(
                "SELECT active FROM participants WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            )).fetchone()
        return bool(row and row["active"])

    async def active_participant_ids(self, guild_id: int) -> list[int]:
        async with self.connection() as db:
            rows = await (await db.execute(
                "SELECT user_id FROM participants WHERE guild_id = ? AND active = 1 ORDER BY joined_at ASC",
                (guild_id,),
            )).fetchall()
        return [int(row["user_id"]) for row in rows]

    async def active_participant_count(self, guild_id: int) -> int:
        async with self.connection() as db:
            row = await (await db.execute(
                "SELECT COUNT(*) AS n FROM participants WHERE guild_id = ? AND active = 1",
                (guild_id,),
            )).fetchone()
        return int(row["n"])

    async def get_open_round(self, guild_id: int):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT * FROM rounds
                WHERE guild_id = ? AND status = 'open'
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id,),
            )).fetchone()

    async def get_active_round(self, guild_id: int):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT * FROM rounds
                WHERE guild_id = ? AND status IN ('open', 'review')
                ORDER BY id DESC LIMIT 1
                """,
                (guild_id,),
            )).fetchone()

    async def create_round(
        self,
        guild_id: int,
        channel_id: int,
        master_id: int,
        solution: str,
        image_url: str | None,
        hint_1: str,
        hint_2: str,
        hint_3: str,
        started_at: str,
        ends_at: str,
        hint_1_scheduled_at: str,
        hint_2_scheduled_at: str,
        hint_3_scheduled_at: str,
    ) -> int:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO rounds(
                    guild_id, channel_id, master_id, solution, image_url,
                    hint_1, hint_2, hint_3,
                    hint_1_scheduled_at, hint_2_scheduled_at, hint_3_scheduled_at,
                    started_at, ends_at, original_ends_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')
                """,
                (
                    guild_id, channel_id, master_id, solution, image_url,
                    hint_1, hint_2, hint_3,
                    hint_1_scheduled_at, hint_2_scheduled_at, hint_3_scheduled_at,
                    started_at, ends_at, ends_at,
                ),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def update_round_image_url(self, round_id: int, image_url: str | None) -> None:
        async with self.connection() as db:
            await db.execute(
                "UPDATE rounds SET image_url = ? WHERE id = ?",
                (image_url, round_id),
            )
            await db.commit()

    async def open_rounds(self):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT * FROM rounds
                WHERE status = 'open'
                ORDER BY started_at ASC
                """
            )).fetchall()

    async def mark_hint_revealed(self, round_id: int, hint_number: int, revealed_at: str) -> bool:
        if hint_number not in {1, 2, 3}:
            raise ValueError("Numéro d’indice invalide")
        column = f"hint_{hint_number}_revealed_at"
        async with self.connection() as db:
            cursor = await db.execute(
                f"UPDATE rounds SET {column} = ? WHERE id = ? AND {column} IS NULL",
                (revealed_at, round_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def accelerate_round(
        self,
        round_id: int,
        accelerated_at: str,
        ends_at: str,
        hint_1_scheduled_at: str,
        hint_2_scheduled_at: str,
        hint_3_scheduled_at: str,
    ) -> bool:
        """Active le mode accéléré une seule fois pour une manche encore ouverte."""
        async with self.connection() as db:
            cursor = await db.execute(
                """
                UPDATE rounds
                SET accelerated_at = ?,
                    ends_at = ?,
                    hint_1_scheduled_at = ?,
                    hint_2_scheduled_at = ?,
                    hint_3_scheduled_at = ?
                WHERE id = ? AND status = 'open' AND accelerated_at IS NULL
                """,
                (
                    accelerated_at, ends_at,
                    hint_1_scheduled_at, hint_2_scheduled_at, hint_3_scheduled_at,
                    round_id,
                ),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def create_attempt(self, guild_id: int, round_id: int, user_id: int, answer: str) -> int:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                INSERT INTO attempts(guild_id, round_id, user_id, answer, submitted_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, round_id, user_id, answer, utcnow_iso()),
            )
            await db.commit()
            return int(cursor.lastrowid)

    async def get_attempt(self, attempt_id: int):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT a.*, r.master_id, r.status AS round_status
                FROM attempts a
                JOIN rounds r ON r.id = a.round_id
                WHERE a.id = ?
                """,
                (attempt_id,),
            )).fetchone()

    async def review_attempt(self, attempt_id: int, reviewer_id: int, status: str) -> bool:
        if status not in {"correct", "incorrect"}:
            raise ValueError("Statut de validation invalide")
        async with self.connection() as db:
            cursor = await db.execute(
                """
                UPDATE attempts
                SET status = ?, reviewed_at = ?, reviewed_by = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, utcnow_iso(), reviewer_id, attempt_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def pending_attempts(self, round_id: int):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT * FROM attempts
                WHERE round_id = ? AND status = 'pending'
                ORDER BY submitted_at ASC
                """,
                (round_id,),
            )).fetchall()

    async def count_attempts(self, round_id: int) -> int:
        async with self.connection() as db:
            row = await (await db.execute(
                "SELECT COUNT(*) AS n FROM attempts WHERE round_id = ?", (round_id,)
            )).fetchone()
            return int(row["n"])

    async def due_rounds(self, now_iso: str):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT * FROM rounds
                WHERE status = 'open' AND ends_at <= ?
                ORDER BY ends_at ASC
                """,
                (now_iso,),
            )).fetchall()

    async def get_round(self, round_id: int):
        async with self.connection() as db:
            return await (await db.execute(
                "SELECT * FROM rounds WHERE id = ?", (round_id,)
            )).fetchone()

    async def lock_round_for_review(self, round_id: int) -> bool:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                UPDATE rounds SET status = 'review'
                WHERE id = ? AND status = 'open'
                """,
                (round_id,),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def close_round(self, round_id: int) -> bool:
        async with self.connection() as db:
            cursor = await db.execute(
                """
                UPDATE rounds SET status = 'closed', closed_at = ?
                WHERE id = ? AND status IN ('open', 'review')
                """,
                (utcnow_iso(), round_id),
            )
            await db.commit()
            return cursor.rowcount == 1

    async def first_correct_by_user(self, round_id: int):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT user_id, MIN(submitted_at) AS submitted_at
                FROM attempts
                WHERE round_id = ? AND status = 'correct'
                GROUP BY user_id
                ORDER BY submitted_at ASC
                """,
                (round_id,),
            )).fetchall()

    async def add_score(self, guild_id: int, user_id: int, points: int, reason: str, round_id: int | None = None) -> None:
        async with self.connection() as db:
            await db.execute(
                """
                INSERT INTO score_events(guild_id, user_id, round_id, points, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, round_id, points, reason, utcnow_iso()),
            )
            await db.commit()

    async def leaderboard(self, guild_id: int, limit: int = 50):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT user_id, COALESCE(SUM(points), 0) AS score
                FROM score_events
                WHERE guild_id = ?
                GROUP BY user_id
                ORDER BY score DESC, user_id ASC
                LIMIT ?
                """,
                (guild_id, limit),
            )).fetchall()

    async def user_score(self, guild_id: int, user_id: int) -> int:
        async with self.connection() as db:
            row = await (await db.execute(
                """
                SELECT COALESCE(SUM(points), 0) AS score
                FROM score_events
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )).fetchone()
            return int(row["score"])


    async def user_stats(self, guild_id: int, user_id: int) -> dict[str, int | None]:
        """Statistiques calculées uniquement à partir des manches clôturées.

        Les bonnes réponses de la manche en cours ne sont jamais exposées par cette
        méthode afin de préserver le caractère secret du jeu.
        """
        async with self.connection() as db:
            score_row = await (await db.execute(
                """
                SELECT COALESCE(SUM(points), 0) AS score
                FROM score_events
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )).fetchone()
            score = int(score_row["score"])

            podium_row = await (await db.execute(
                """
                SELECT
                    SUM(CASE WHEN reason = 'podium_1' THEN 1 ELSE 0 END) AS firsts,
                    SUM(CASE WHEN reason = 'podium_2' THEN 1 ELSE 0 END) AS seconds,
                    SUM(CASE WHEN reason = 'podium_3' THEN 1 ELSE 0 END) AS thirds,
                    SUM(CASE WHEN reason = 'unfound_master_bonus' THEN 1 ELSE 0 END) AS unfound
                FROM score_events
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )).fetchone()

            master_row = await (await db.execute(
                """
                SELECT COUNT(*) AS n
                FROM rounds
                WHERE guild_id = ? AND master_id = ? AND status = 'closed'
                """,
                (guild_id, user_id),
            )).fetchone()

            participation_row = await (await db.execute(
                """
                SELECT COUNT(DISTINCT a.round_id) AS n
                FROM attempts a
                JOIN rounds r ON r.id = a.round_id
                WHERE a.guild_id = ? AND a.user_id = ? AND r.status = 'closed'
                """,
                (guild_id, user_id),
            )).fetchone()

            correct_row = await (await db.execute(
                """
                SELECT COUNT(DISTINCT a.round_id) AS n
                FROM attempts a
                JOIN rounds r ON r.id = a.round_id
                WHERE a.guild_id = ? AND a.user_id = ?
                  AND a.status = 'correct' AND r.status = 'closed'
                """,
                (guild_id, user_id),
            )).fetchone()

            rank_rows = await (await db.execute(
                """
                SELECT user_id, COALESCE(SUM(points), 0) AS score
                FROM score_events
                WHERE guild_id = ?
                GROUP BY user_id
                ORDER BY score DESC, user_id ASC
                """,
                (guild_id,),
            )).fetchall()
            rank = next((i for i, row in enumerate(rank_rows, start=1) if row["user_id"] == user_id), None)

        return {
            "score": score,
            "rank": rank,
            "participations": int(participation_row["n"]),
            "correct_rounds": int(correct_row["n"]),
            "firsts": int(podium_row["firsts"] or 0),
            "seconds": int(podium_row["seconds"] or 0),
            "thirds": int(podium_row["thirds"] or 0),
            "rounds_as_master": int(master_row["n"]),
            "unfound": int(podium_row["unfound"] or 0),
        }

    async def history(self, guild_id: int, limit: int = 10):
        async with self.connection() as db:
            return await (await db.execute(
                """
                SELECT * FROM rounds
                WHERE guild_id = ? AND status = 'closed'
                ORDER BY id DESC LIMIT ?
                """,
                (guild_id, limit),
            )).fetchall()
