"""ffmpeg / ffprobe helpers."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from . import config


class FFmpegMissing(RuntimeError):
    pass


INSTALL_HELP = (
    "ffmpeg/ffprobe not found.\n"
    f"  Recommended (keeps C: untouched): download the 'essentials' build from "
    f"https://www.gyan.dev/ffmpeg/builds/ and copy ffmpeg.exe + ffprobe.exe into:\n    {config.BIN}\n"
    "  Alternative: winget install Gyan.FFmpeg   (installs under C:, then reopen the terminal)."
)


def find_tool(name: str) -> str:
    """Look in the bundled bin/, then <root>/bin, then PATH."""
    for d in (config.BUNDLED_BIN, config.BIN):
        for cand in (d / f"{name}.exe", d / name):
            if cand.is_file():
                return str(cand)
    found = shutil.which(name)
    if found:
        return found
    raise FFmpegMissing(INSTALL_HELP)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def duration(path: Path) -> float:
    r = _run([find_tool("ffprobe"), "-v", "error", "-show_entries", "format=duration",
              "-of", "default=nw=1:nk=1", str(path)])
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe failed on {path}: {r.stderr.strip()}")
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(f"could not read duration of {path}")


def has_audio(path: Path) -> bool:
    r = _run([find_tool("ffprobe"), "-v", "error", "-select_streams", "a",
              "-show_entries", "stream=index", "-of", "csv=p=0", str(path)])
    return r.returncode == 0 and bool(r.stdout.strip())


def has_video(path: Path) -> bool:
    r = _run([find_tool("ffprobe"), "-v", "error", "-select_streams", "v:0",
              "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)])
    return r.returncode == 0 and "video" in r.stdout


def burn_subtitles(video: Path, subtitle_text: str, fmt: str, dst: Path) -> Path:
    """Hard-burn subtitles with the libass 'subtitles' filter.

    The subtitle is copied to a simple name in .tmp and ffmpeg runs with that as cwd,
    which sidesteps Windows drive-letter/quote escaping inside filter strings.
    """
    from . import config

    config.TMP.mkdir(parents=True, exist_ok=True)
    work = config.TMP / f"burn-{dst.stem[:20].encode('ascii', 'ignore').decode() or 'x'}-{id(dst) & 0xFFFF}"
    work.mkdir(parents=True, exist_ok=True)
    sub = work / f"s.{fmt}"
    sub.write_text(subtitle_text, encoding="utf-8")
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [find_tool("ffmpeg"), "-y", "-v", "error", "-i", str(video.resolve()),
             "-vf", f"subtitles=s.{fmt}", "-c:a", "copy", str(dst.resolve())],
            capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=work,
        )
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if r.returncode != 0:
        dst.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg could not burn subtitles: {r.stderr.strip()[-500:]}")
    return dst


def extract_audio(src: Path, dst: Path) -> Path:
    """16 kHz mono PCM wav, the format Whisper expects."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    r = _run([find_tool("ffmpeg"), "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1",
              "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg could not extract audio from {src}: {r.stderr.strip()}")
    return dst
