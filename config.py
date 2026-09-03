from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    token: str
    database_path: Path
    environment: str
    command_guild_ids: tuple[int, ...]
    bot_owner_user_id: int | None
    legacy_guild_id: int | None
    legacy_game_channel_id: int | None
    legacy_game_admin_role_id: int | None
    round_duration_days: int = 7


def _optional_int(name: str) -> int | None:
    value = os.getenv(name, "").strip()
    return int(value) if value else None


def _command_guild_ids() -> tuple[int, ...]:
    raw_values = os.getenv("COMMAND_GUILD_IDS", "").strip()
    guild_ids: list[int] = []

    if raw_values:
        for raw_value in raw_values.split(","):
            value = raw_value.strip()
            if not value:
                continue
            try:
                guild_id = int(value)
            except ValueError as exc:
                raise RuntimeError(
                    "COMMAND_GUILD_IDS doit contenir uniquement des IDs Discord séparés par des virgules."
                ) from exc
            if guild_id not in guild_ids:
                guild_ids.append(guild_id)

    if guild_ids:
        return tuple(guild_ids)

    # Compatibilité avec les anciennes configurations de staging :
    # utilisée uniquement si COMMAND_GUILD_IDS est vide/non défini.
    legacy_guild_id = _optional_int("COMMAND_GUILD_ID")
    return (legacy_guild_id,) if legacy_guild_id is not None else ()


def load_config() -> Config:
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("La variable DISCORD_TOKEN est obligatoire.")

    environment = os.getenv("ENVIRONMENT", "production").strip().lower() or "production"
    if environment not in {"production", "staging", "development"}:
        raise RuntimeError("ENVIRONMENT doit valoir production, staging ou development.")

    return Config(
        token=token,
        database_path=Path(os.getenv("DATABASE_PATH", "data/scoreboard.db")),
        environment=environment,
        command_guild_ids=_command_guild_ids(),
        bot_owner_user_id=_optional_int("BOT_OWNER_USER_ID"),
        # Compatibilité de migration depuis la branche mono-serveur v0.13.x.
        legacy_guild_id=_optional_int("GUILD_ID"),
        legacy_game_channel_id=_optional_int("GAME_CHANNEL_ID"),
        legacy_game_admin_role_id=_optional_int("GAME_ADMIN_ROLE_ID"),
        round_duration_days=int(os.getenv("ROUND_DURATION_DAYS", "7")),
    )
