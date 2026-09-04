import asyncio
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from database import Database


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "test.db")
        await db.init()
        await db.configure_guild(100, 1001, None)
        period = await db.get_current_period(100)
        now = datetime.now(timezone.utc)
        round_id = await db.create_round(
            100, 1001, 10, period["id"], 3, "Game", None,
            "h1", "h2", "h3",
            now.isoformat(), (now + timedelta(days=7)).isoformat(),
            (now + timedelta(days=2)).isoformat(),
            (now + timedelta(days=4)).isoformat(),
            (now + timedelta(days=6)).isoformat(),
        )

        first = await db.create_attempt(100, round_id, 20, "First")
        assert first is not None
        assert await db.user_pending_attempt_count(round_id, 20) == 1

        second = await db.create_attempt(100, round_id, 20, "Second")
        assert second is None
        assert await db.user_attempt_count(round_id, 20) == 1

        assert await db.review_attempt(first, 10, "incorrect") is True
        third = await db.create_attempt(100, round_id, 20, "Third")
        assert third is not None
        assert await db.user_attempt_count(round_id, 20) == 2

        # The guard is scoped to player + round. The same user may have a pending
        # answer on another server/round without interference.
        await db.configure_guild(200, 2001, None)
        period2 = await db.get_current_period(200)
        round2 = await db.create_round(
            200, 2001, 30, period2["id"], 3, "Other", None,
            "h1", "h2", "h3",
            now.isoformat(), (now + timedelta(days=7)).isoformat(),
            (now + timedelta(days=2)).isoformat(),
            (now + timedelta(days=4)).isoformat(),
            (now + timedelta(days=6)).isoformat(),
        )
        other = await db.create_attempt(200, round2, 20, "Other answer")
        assert other is not None
        assert await db.user_pending_attempt_count(round2, 20) == 1

        print("pending attempt flow: OK")


asyncio.run(main())
