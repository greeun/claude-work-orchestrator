import json

from config import load_config


def test_defaults_when_no_file(root):
    cfg = load_config(root)
    assert cfg.max_active == 4
    assert cfg.stale_minutes == 30
    assert cfg.test_command == "pytest"
    assert cfg.main_branch == "main"
    assert cfg.worktree_parent is None


def test_config_json_overrides_defaults(root):
    (root / "backlog" / "config.json").write_text(
        json.dumps({"max_active": 8, "test_command": "true"})
    )
    cfg = load_config(root)
    assert cfg.max_active == 8
    assert cfg.test_command == "true"
    # 지정 안 한 값은 기본 유지
    assert cfg.main_branch == "main"


def test_auto_redispatch_default_false(root):
    cfg = load_config(root)
    assert cfg.auto_redispatch is False


def test_auto_redispatch_from_config(root):
    (root / "backlog" / "config.json").write_text(
        json.dumps({"auto_redispatch": True})
    )
    assert load_config(root).auto_redispatch is True
