from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    token: str
    guild_id: int | None
    game_channel_id: int | None
    game_admin_role_id: int | None
    database_path: Path
    round_duration_days: int = 7


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("La variable DISCORD_TOKEN est obligatoire.")

    return Config(
        token=token,
        guild_id=_optional_int("GUILD_ID"),
        game_channel_id=_optional_int("GAME_CHANNEL_ID"),
        game_admin_role_id=_optional_int("GAME_ADMIN_ROLE_ID"),
        database_path=Path(os.getenv("DATABASE_PATH", "data/scoreboard.db")),
        round_duration_days=int(os.getenv("ROUND_DURATION_DAYS", "7")),
    )
