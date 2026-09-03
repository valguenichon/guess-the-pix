import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "bot.py"
text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(text)


def method(name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")

policy = ast.get_source_segment(text, method("uses_guild_scoped_commands")) or ""
assert '"staging", "development"' in policy

join_source = ast.get_source_segment(text, method("on_guild_join")) or ""
assert "uses_guild_scoped_commands" in join_source
assert "sync_commands_to_guild" in join_source
assert "guild.id in config.command_guild_ids" not in join_source

ready_source = ast.get_source_segment(text, method("on_ready")) or ""
assert "uses_guild_scoped_commands" in ready_source
assert "sync_commands_to_guild" in ready_source

setup_source = ast.get_source_segment(text, method("setup_hook")) or ""
assert "for guild_id in config.command_guild_ids" in setup_source
assert "COMMAND_GUILD_IDS est ignore en production" in setup_source
assert "await self.tree.sync()" in setup_source

print("optional command guild ids policy: OK")
