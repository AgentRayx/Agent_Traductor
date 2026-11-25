"""Central configuration. Forces all caches/temp onto the project drive.

Import this module BEFORE faster_whisper / huggingface_hub / argostranslate so
their cache paths are resolved under the project root (never on C:).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))  # running as the PyInstaller exe
PORTABLE_MARKER = "portable.flag"


def _user_data_dir() -> Path:
    """Installed mode: per-user writable folder (LOCALAPPDATA/subforge on Windows)."""
    base = (os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME")
            or str(Path.home() / ".local" / "share"))
    return Path(base) / "subforge"


def _writable(d: Path) -> bool:
    try:
        probe = d / ".subforge_write_test"
        probe.write_text("x")
        probe.unlink()
        return True
    except OSError:
        return False


def resolve_dirs(frozen: bool, exe_dir: Path, source_root: Path, env_root=None):
    """Return (APP_DIR, ROOT). APP_DIR holds the program (and bundled bin/); ROOT holds data.

    - dev (source checkout): both are the project root.
    - frozen + portable.flag next to the exe (the zip build): data lives next to the exe.
    - frozen without the flag (installed in Program Files): data in the per-user folder.
    """
    if frozen:
        app = exe_dir
        if env_root:
            return app, Path(env_root).resolve()
        if (app / PORTABLE_MARKER).is_file() and _writable(app):
            return app, app
        return app, _user_data_dir()
    root = Path(env_root or source_root).resolve()
    return root, root


APP_DIR, ROOT = resolve_dirs(FROZEN, Path(sys.executable).resolve().parent,
                             Path(__file__).resolve().parents[2], os.environ.get("SUBFORGE_ROOT"))
BUNDLED_BIN = APP_DIR / "bin"  # ffmpeg/tesseract shipped inside the exe package

CACHE = ROOT / ".cache"
DATA = ROOT / ".data"
TMP = ROOT / ".tmp"
LOGS = ROOT / ".logs"
BIN = ROOT / "bin"
DEFAULT_OUT = ROOT / "out"

DEFAULT_MANGA_TIMEOUT = 3600  # seconds


def manga_timeout() -> int:
    """'manga_timeout': max seconds the external manga backend may run; 0 = no limit.
    Set with env SUBFORGE_MANGA_TIMEOUT (or `subforge manga --timeout`)."""
    raw = os.environ.get("SUBFORGE_MANGA_TIMEOUT", "").strip()
    try:
        return max(0, int(raw)) if raw else DEFAULT_MANGA_TIMEOUT
    except ValueError:
        return DEFAULT_MANGA_TIMEOUT


_FORCED = {
    "HF_HOME": CACHE / "hf",
    "XDG_CACHE_HOME": CACHE,
    "XDG_DATA_HOME": DATA,
    "PIP_CACHE_DIR": CACHE / "pip",
    "TMP": TMP,
    "TEMP": TMP,
}


def _under_root(value: str) -> bool:
    try:
        Path(value).resolve().relative_to(ROOT)
        return True
    except (ValueError, OSError):
        return False


def setup_environment() -> None:
    """Point every cache variable at the project; override values pointing elsewhere."""
    for key, path in _FORCED.items():
        path.mkdir(parents=True, exist_ok=True)
        current = os.environ.get(key)
        if not current or not _under_root(current):
            os.environ[key] = str(path)
    LOGS.mkdir(parents=True, exist_ok=True)
    BIN.mkdir(parents=True, exist_ok=True)
    # tempfile may already have cached its dir
    import tempfile

    tempfile.tempdir = str(TMP)
    # Offline translation: never let Argos/HF phone home implicitly.
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


setup_environment()
