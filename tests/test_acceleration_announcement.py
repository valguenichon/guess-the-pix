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


trigger = ast.get_source_segment(text, method("trigger_acceleration")) or ""
sender = ast.get_source_segment(text, method("send_acceleration_announcement")) or ""
shared = ast.get_source_segment(text, method("send_round_action_announcement")) or ""

# The refreshed round determines the destination channel/guild; no participant/user
# lookup is involved in choosing where acceleration is announced.
assert 'refreshed["channel_id"]' in trigger
assert 'refreshed["guild_id"]' in trigger
assert "send_acceleration_announcement" in trigger

# Acceleration delegates to the common resilient round-announcement path.
assert "send_round_action_announcement" in sender
assert "prepare_round_repost_image" in shared
assert "file=image_file" in shared
assert "await channel.send(content=content, view=RoundActionsView(self))" in shared
assert "await channel.send(content=content)" in shared
assert "logger.warning" in shared
assert "logger.exception" in shared

print("acceleration announcement fallback: OK")
