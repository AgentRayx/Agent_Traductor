"""SRT / VTT serialisation."""
from __future__ import annotations

from typing import Iterable

from .segments import Cue


def format_timestamp(seconds: float, sep: str = ",") -> str:
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _check(cues: list[Cue]) -> None:
    prev_end = 0.0
    for i, c in enumerate(cues, 1):
        if c.end <= c.start:
            raise ValueError(f"cue {i}: end ({c.end}) must be > start ({c.start})")
        if c.start + 1e-6 < prev_end:
            raise ValueError(f"cue {i}: overlaps previous cue")
        prev_end = c.end


def to_srt(cues: Iterable[Cue]) -> str:
    cues = list(cues)
    _check(cues)
    blocks = []
    for i, c in enumerate(cues, 1):
        blocks.append(
            f"{i}\n{format_timestamp(c.start, ',')} --> {format_timestamp(c.end, ',')}\n{c.text}\n"
        )
    return "\n".join(blocks)


def to_vtt(cues: Iterable[Cue]) -> str:
    cues = list(cues)
    _check(cues)
    blocks = ["WEBVTT\n"]
    for c in cues:
        blocks.append(
            f"{format_timestamp(c.start, '.')} --> {format_timestamp(c.end, '.')}\n{c.text}\n"
        )
    return "\n".join(blocks)


def render(cues: Iterable[Cue], fmt: str) -> str:
    if fmt == "srt":
        return to_srt(cues)
    if fmt == "vtt":
        return to_vtt(cues)
    raise ValueError(f"unknown format: {fmt!r} (use srt or vtt)")
