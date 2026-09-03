from pathlib import Path


def test_bot_created_admin_role_name_is_fixed():
    source = (Path(__file__).resolve().parents[1] / "bot.py").read_text(encoding="utf-8")
    assert 'ADMIN_ROLE_NAME = "Guess the Pix - admin"' in source
    assert 'name=ADMIN_ROLE_NAME' in source
    assert 'role_admin is not None and creer_role_admin' in source
