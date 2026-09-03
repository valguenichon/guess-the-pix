import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "bot.py"
text = SOURCE.read_text(encoding="utf-8")
tree = ast.parse(text)


def method(name: str) -> ast.AsyncFunctionDef | ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")


header = method("guild_dm_header")
header_source = ast.get_source_segment(text, header) or ""
assert "Serveur" in header_source
assert "guild_display_name" in header_source

notify = method("notify_leader")
notify_source = ast.get_source_segment(text, notify) or ""
assert 'name="Serveur"' in notify_source
assert "guild_display_name" in notify_source

for node in ast.walk(tree):
    if not isinstance(node, ast.Call):
        continue
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "send_player_message"
        and isinstance(func.value, ast.Name)
        and func.value.id == "self"
    ):
        assert len(node.args) >= 3, "send_player_message must receive guild_id, user_id and message"

assert "await master.send(" not in text
assert "La manche #{round_id}" not in text

print("guild DM context: OK")
