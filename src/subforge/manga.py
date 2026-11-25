"""Optional EXTERNAL manga backend (manga-image-translator). Never installed in our venv.

Detection order:
  1. env SUBFORGE_MANGA_CMD      full command prefix, e.g. "D:\\mt\\.venv\\Scripts\\python.exe -m manga_translator"
  2. env SUBFORGE_MANGA_PYTHON   python of a separate venv that has manga_translator installed
  3. <project>\\bin\\manga_translator.exe, or `manga_translator` / `manga-image-translator` on PATH

NOTE: the exact CLI of manga-image-translator changes between releases; the invocation below
(`local -i IN -o OUT --config-file cfg.json`, then `--mode batch ...`) is only exercised in tests
through a stand-in backend. SUBFORGE_MANGA_ARGS overrides the command line; see the README.
"""
from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import List, Optional

from . import config
from .logging_setup import log

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
LANG_CODES = {"es": "ESP", "en": "ENG", "fr": "FRA", "de": "DEU", "it": "ITA", "pt": "PTB",
              "ja": "JPN", "zh": "CHS", "ru": "RUS", "ko": "KOR"}

INSTALL_HELP = (
    "Manga backend not found. It is optional and must live OUTSIDE this venv (torch + models weigh GBs):\n"
    "  1. Install manga-image-translator in its own venv (see its README), e.g. D:\\dev\\manga-mt\\.venv\n"
    "  2. Tell subforge where it is:\n"
    '     $env:SUBFORGE_MANGA_PYTHON = "D:\\dev\\manga-mt\\.venv\\Scripts\\python.exe"\n'
    "     (or set SUBFORGE_MANGA_CMD to the full command prefix)"
)


def find_backend() -> Optional[List[str]]:
    cmd = os.environ.get("SUBFORGE_MANGA_CMD")
    if cmd:
        return [t.strip('"') for t in shlex.split(cmd, posix=False)]  # keep Windows backslashes
    py = os.environ.get("SUBFORGE_MANGA_PYTHON")
    if py and Path(py).is_file():
        return [py, "-m", "manga_translator"]
    for cand in (config.BIN / "manga_translator.exe",):
        if cand.is_file():
            return [str(cand)]
    for name in ("manga_translator", "manga-image-translator"):
        w = shutil.which(name)
        if w:
            return [w]
    return None


def available() -> bool:
    return find_backend() is not None


# CLI templates tried in order (the CLI of manga-image-translator changed between releases).
# Placeholders: {IN} {OUT} {CFG}. SUBFORGE_MANGA_ARGS replaces this list with a single template.
TEMPLATES = (
    ["local", "-i", "{IN}", "-o", "{OUT}", "--config-file", "{CFG}"],
    ["--mode", "batch", "-i", "{IN}", "-o", "{OUT}", "--config-file", "{CFG}"],
)


def _templates() -> List[List[str]]:
    custom = os.environ.get("SUBFORGE_MANGA_ARGS", "").strip()
    if custom:
        return [[t.strip('"') for t in shlex.split(custom, posix=False)]]
    return [list(t) for t in TEMPLATES]


def _fill(template: List[str], inp: Path, out_dir: Path, cfg: Path) -> List[str]:
    m = {"{IN}": str(inp), "{OUT}": str(out_dir), "{CFG}": str(cfg)}
    return [m.get(t) or t.replace("{IN}", m["{IN}"]).replace("{OUT}", m["{OUT}"])
            .replace("{CFG}", m["{CFG}"]) for t in template]


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
        else:
            os.killpg(proc.pid, 9)
    except Exception:
        pass
    proc.kill()


class BackendTimeout(RuntimeError):
    pass


def _run_once(argv: List[str], timeout: int):
    kw = {"start_new_session": True} if os.name != "nt" else {}
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **kw)
    try:
        out, err = proc.communicate(timeout=timeout or None)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        proc.communicate()
        raise BackendTimeout(
            f"manga backend timeout: killed after {timeout}s (raise it with SUBFORGE_MANGA_TIMEOUT "
            "or `subforge manga --timeout SECONDS`; 0 = no limit)") from None
    return proc.returncode, out or "", err or ""


def _has_images(d: Path) -> bool:
    return any(p.is_file() and p.suffix.lower() in IMAGE_EXT for p in d.rglob("*"))


def _run_backend(cmd: List[str], inp: Path, out_dir: Path, target: str) -> None:
    code = LANG_CODES.get(target)
    if not code:
        raise ValueError(f"unsupported manga target language: {target!r}")
    timeout = config.manga_timeout()
    cfg = config.TMP / f"manga-{uuid.uuid4().hex}.json"
    cfg.write_text(json.dumps({"translator": {"target_lang": code}}), encoding="utf-8")
    failures: List[str] = []
    try:
        for tpl in _templates():
            argv = [*cmd, *_fill(tpl, inp, out_dir, cfg)]
            log.info("manga backend: %s", " ".join(tpl))
            rc, so, se = _run_once(argv, timeout)  # BackendTimeout aborts: retrying would double the wait
            if rc == 0 and _has_images(out_dir):
                return
            why = f"exit {rc}" if rc else "exit 0 but it produced no images"
            failures.append(f"[{' '.join(tpl)}] {why}: {(se or so).strip()[-600:] or '(no output)'}")
            for p in out_dir.iterdir():  # discard partial output before the next attempt
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
    finally:
        cfg.unlink(missing_ok=True)
    raise RuntimeError(
        "manga backend failed with every CLI template tried:\n" + "\n".join(failures) +
        "\nIf your backend uses a different command line, set SUBFORGE_MANGA_ARGS, e.g. "
        '"local -i {IN} -o {OUT} --config-file {CFG}" (args after the command prefix).')


def flatten_images(src: Path, dst: Path) -> int:
    """Copy every image under `src` (recursively) into the flat folder `dst`. Name clashes get a
    numeric suffix: a/001.png + b/001.png -> 001.png, 001_1.png. Returns the number copied."""
    used, n = set(), 0
    for f in sorted(p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT):
        name, i = f.name, 0
        while name.lower() in used:
            i += 1
            name = f"{f.stem}_{i}{f.suffix}"
        used.add(name.lower())
        shutil.copy2(f, dst / name)
        n += 1
    return n


def translate_path(src: Path, out_dir: Path, target: str = "es") -> Path:
    """image | folder | .cbz -> translated copy in out_dir. Returns the output path."""
    from .cli import unique_path

    cmd = find_backend()
    if not cmd:
        raise RuntimeError(INSTALL_HELP)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = config.TMP / f"manga-{uuid.uuid4().hex}"
    (work / "in").mkdir(parents=True)
    (work / "out").mkdir()
    try:
        if src.suffix.lower() == ".cbz":
            with zipfile.ZipFile(src) as z:
                for m in z.namelist():  # extract images only; guard against path traversal
                    if Path(m).suffix.lower() in IMAGE_EXT and not Path(m).is_absolute() and ".." not in Path(m).parts:
                        z.extract(m, work / "in")
            inp = work / "in"
        elif src.is_dir():
            flatten_images(src, work / "in")
            inp = work / "in"
        elif src.suffix.lower() in IMAGE_EXT:
            shutil.copy2(src, work / "in" / src.name)
            inp = work / "in" / src.name
        else:
            raise ValueError("manga input must be an image, a folder of images or a .cbz")
        if not any(p.is_file() for p in (work / "in").rglob("*")):
            raise ValueError("no images found in the input")
        log.info("running manga backend (%s) ...", cmd[0])
        _run_backend(cmd, inp, work / "out", target)
        results = sorted(p for p in (work / "out").rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_EXT)
        if not results:
            raise RuntimeError("manga backend produced no images")
        if src.suffix.lower() == ".cbz":
            dst = unique_path(out_dir / f"{src.stem}.{target}.cbz")
            with zipfile.ZipFile(dst, "w", zipfile.ZIP_STORED) as z:
                for p in results:
                    z.write(p, p.relative_to(work / "out").as_posix())
        elif src.is_dir():
            dst = unique_path(out_dir / f"{src.name}.{target}")
            dst.mkdir()
            for p in results:
                shutil.copy2(p, dst / p.name)
        else:
            dst = unique_path(out_dir / f"{src.stem}.{target}{results[0].suffix}")
            shutil.copy2(results[0], dst)
        log.info("wrote %s", dst)
        return dst
    finally:
        shutil.rmtree(work, ignore_errors=True)
