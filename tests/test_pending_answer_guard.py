import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
bot_text = (ROOT / "bot.py").read_text(encoding="utf-8")
db_text = (ROOT / "database.py").read_text(encoding="utf-8")
bot_tree = ast.parse(bot_text)
db_tree = ast.parse(db_text)


def method(tree, name: str):
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"method {name!r} not found")


answer_source = ast.get_source_segment(bot_text, method(bot_tree, "answer")) or ""
create_source = ast.get_source_segment(db_text, method(db_tree, "create_attempt")) or ""

assert "user_pending_attempt_count" in answer_source
assert "déjà une réponse en attente de validation" in answer_source
assert "attempt_id is None" in answer_source
assert "BEGIN IMMEDIATE" in create_source
assert "status = 'pending'" in create_source
assert "return None" in create_source

print("pending answer guard: OK")
