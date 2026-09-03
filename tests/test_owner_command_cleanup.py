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


cleanup = method("owner_cleanup_commands")
source = ast.get_source_segment(text, cleanup) or ""
assert 'name="nettoyer-commandes"' in text
assert "require_bot_owner" in source
assert "parse_guild_id" in source
assert "bot.tree.clear_commands" in source
assert "await bot.tree.sync" in source
assert "guild=guild_object" in source
assert "db." not in source, "command cleanup must not mutate game data"
assert "Les commandes globales" in source

print("owner command cleanup: OK")
