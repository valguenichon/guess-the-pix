import os
from unittest.mock import patch

from config import _command_guild_ids


def check(env, expected):
    with patch.dict(os.environ, env, clear=True):
        assert _command_guild_ids() == expected


check({"COMMAND_GUILD_IDS": "100,200"}, (100, 200))
check({"COMMAND_GUILD_IDS": " 100, 200,100 "}, (100, 200))
check({"COMMAND_GUILD_ID": "300"}, (300,))
check({"COMMAND_GUILD_IDS": "100,200", "COMMAND_GUILD_ID": "300"}, (100, 200))
check({}, ())

try:
    with patch.dict(os.environ, {"COMMAND_GUILD_IDS": "100,nope"}, clear=True):
        _command_guild_ids()
except RuntimeError:
    pass
else:
    raise AssertionError("invalid COMMAND_GUILD_IDS should raise RuntimeError")

print("command guild ids: OK")
