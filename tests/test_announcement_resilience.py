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


hints = ast.get_source_segment(text, method("publish_due_hints")) or ""
shared = ast.get_source_segment(text, method("send_round_action_announcement")) or ""
round_end = ast.get_source_segment(text, method("send_round_end_announcements")) or ""
period_end = ast.get_source_segment(text, method("send_period_end_announcement")) or ""
finish = ast.get_source_segment(text, method("finish_round")) or ""

# Hints cannot be published concurrently by the scheduler and acceleration path.
assert "self._hint_publish_lock = asyncio.Lock()" in text
assert "async with self._hint_publish_lock" in hints
assert "send_round_action_announcement" in hints
assert "if hint_message is None" in hints
assert "mark_hint_revealed" in hints

# Rich round announcements retry without the screenshot, then without components.
assert "prepare_round_repost_image" in shared
assert "file=image_file" in shared
assert "view=RoundActionsView(self)" in shared
assert "await channel.send(content=content)" in shared
assert "logger.exception" in shared

# End-of-round header retries without the image; detail failure is caught independently.
assert "file=image_file" in round_end
assert "if not header_sent" in round_end
assert "await channel.send(content=result_content)" in round_end
assert "await channel.send(content=result_details)" in round_end
assert "La finalisation et la mise a jour des scores continuent" in round_end
assert "send_round_end_announcements" in finish

# Period-end embed has a text fallback and cannot interrupt finalization.
assert "await channel.send(embed=period_embed)" in period_end
assert "await channel.send(content=fallback_content)" in period_end
assert "send_period_end_announcement" in finish
assert "await self.update_scoreboard" in finish

print("announcement resilience: OK")
