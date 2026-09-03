import asyncio
import tempfile
from pathlib import Path

from database import Database


async def main():
    with tempfile.TemporaryDirectory() as tmp:
        db = Database(Path(tmp) / "authorization.db")
        await db.init()

        status, created = await db.register_guild_join(100, "Guild A", 10)
        assert (status, created) == ("pending", True)
        assert (await db.get_guild_registration(100))["status"] == "pending"

        await db.set_guild_registration_status(100, "approved")
        assert (await db.get_guild_registration(100))["status"] == "approved"

        await db.configure_guild(100, 1001, None)
        assert (await db.get_guild_registration(100))["status"] == "configured"
        assert await db.get_guild_config(100) is not None

        await db.mark_guild_inactive(100)
        assert (await db.get_guild_registration(100))["status"] == "inactive"
        assert await db.get_guild_config(100) is None

        status, created = await db.register_guild_join(100, "Guild A", 10)
        assert (status, created) == ("pending", True)


        # A refusal is distinct from an ordinary inactive server and must survive
        # the guild-remove event caused by the bot leaving the server.
        await db.set_guild_registration_status(100, "refused")
        await db.mark_guild_inactive(100)
        assert (await db.get_guild_registration(100))["status"] == "refused"

        # Reinstalling a refused server creates a fresh pending request, allowing
        # the caller to warn the bot owner that this server was refused before.
        status, created = await db.register_guild_join(100, "Guild A", 10)
        assert (status, created) == ("pending", True)

        await db.set_guild_registration_status(100, "blocked")
        status, created = await db.register_guild_join(100, "Guild A", 10)
        assert (status, created) == ("blocked", False)

        # init() must never convert a blocked guild back to configured.
        await db.init()
        assert (await db.get_guild_registration(100))["status"] == "blocked"

        print("guild authorization workflow: OK")


asyncio.run(main())
