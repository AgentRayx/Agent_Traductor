from pathlib import Path

from subforge import REPO_URL, config
from subforge.cli import build_parser


def test_dev_mode_root_is_source_root(tmp_path):
    app, root = config.resolve_dirs(False, tmp_path / "x", tmp_path)
    assert app == root == tmp_path.resolve()


def test_portable_flag_keeps_data_next_to_exe(tmp_path):
    (tmp_path / config.PORTABLE_MARKER).write_text("")
    assert config.resolve_dirs(True, tmp_path, Path("."), None) == (tmp_path, tmp_path)


def test_installed_uses_user_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    app, root = config.resolve_dirs(True, tmp_path / "ProgramFiles", Path("."), None)
    assert app == tmp_path / "ProgramFiles" and root == tmp_path / "local" / "subforge"


def test_portable_flag_but_read_only_falls_back(tmp_path, monkeypatch):
    (tmp_path / config.PORTABLE_MARKER).write_text("")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(config, "_writable", lambda d: False)
    assert config.resolve_dirs(True, tmp_path, Path("."), None)[1] == tmp_path / "local" / "subforge"


def test_repo_url_placeholder_and_version_flag(capsys):
    assert REPO_URL.endswith("/AgentRayx/Agent_Traductor")
    try:
        build_parser().parse_args(["--version"])
    except SystemExit:
        pass
    assert "subforge" in capsys.readouterr().out
