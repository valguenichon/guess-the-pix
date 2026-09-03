import asyncio
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

from database import Database

async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / 'test.db')
        await db.init()
        await db.configure_guild(100, 1001, 1002)
        await db.configure_guild(200, 2001, None)
        await db.set_participant(100, 11, True)
        await db.set_participant(200, 22, True)
        p100 = await db.get_current_period(100)
        p200 = await db.get_current_period(200)
        now = datetime.now(timezone.utc)
        async def make(gid, channel, master, pid):
            return await db.create_round(
                gid, channel, master, pid, None, 'Game', None,
                'h1','h2','h3', now.isoformat(), (now+timedelta(days=7)).isoformat(),
                (now+timedelta(days=2)).isoformat(), (now+timedelta(days=4)).isoformat(),
                (now+timedelta(days=6)).isoformat())
        r100 = await make(100,1001,11,p100['id'])
        r200 = await make(200,2001,22,p200['id'])
        rr100 = await db.get_round(r100)
        rr200 = await db.get_round(r200)
        assert rr100['round_number'] == 1 and rr200['round_number'] == 1
        assert (await db.active_participant_ids(100)) == [11]
        assert (await db.active_participant_ids(200)) == [22]
        await db.add_score(100, 11, 6, 'test', r100, p100['id'])
        await db.add_score(200, 22, 5, 'test', r200, p200['id'])
        assert (await db.leaderboard(100))[0]['user_id'] == 11
        assert (await db.leaderboard(200))[0]['user_id'] == 22
        await db.reset_guild(100)
        assert await db.get_active_round(100) is None
        assert (await db.active_participant_ids(100)) == []
        assert (await db.active_participant_ids(200)) == [22]
        assert (await db.leaderboard(200))[0]['score'] == 5
        r100b = await make(100,1001,11,(await db.get_current_period(100))['id'])
        assert (await db.get_round(r100b))['round_number'] == 1
        print('multiguild isolation: OK')

asyncio.run(main())
