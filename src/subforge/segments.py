"""Segment model and long-line splitting."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

MAX_CHARS = 42
MAX_LINES = 2
MAX_DURATION = 7.0
MIN_DURATION = 0.4
_PUNCT = tuple(".!?…,;:。！？，")


@dataclass
class Word:
    start: float
    end: float
    text: str


@dataclass
class Segment:
    start: float
    end: float
    text: str
    words: Optional[List[Word]] = field(default=None)


@dataclass
class Cue:
    start: float
    end: float
    text: str  # may contain "\n"


def wrap_lines(text: str, max_chars: int = MAX_CHARS, max_lines: int = MAX_LINES) -> str:
    """Wrap text into at most max_lines balanced lines (best effort)."""
    text = " ".join(text.split())
    if len(text) <= max_chars or max_lines <= 1:
        return text
    words = text.split(" ")
    # choose the break that best balances two lines
    best, best_score = None, None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        over = max(0, len(a) - max_chars) + max(0, len(b) - max_chars)
        score = (over, abs(len(a) - len(b)))
        if best_score is None or score < best_score:
            best, best_score = (a, b), score
    return "\n".join(best) if best else text


def _words_of(seg: Segment) -> List[Word]:
    if seg.words:
        return [Word(w.start, w.end, w.text.strip()) for w in seg.words if w.text.strip()]
    tokens = seg.text.split()
    if not tokens:
        return []
    total = sum(len(t) + 1 for t in tokens)
    dur = max(seg.end - seg.start, 0.0)
    out, t = [], seg.start
    for tok in tokens:
        d = dur * (len(tok) + 1) / total
        out.append(Word(t, t + d, tok))
        t += d
    return out


def split_segment(
    seg: Segment,
    max_chars: int = MAX_CHARS,
    max_lines: int = MAX_LINES,
    max_duration: float = MAX_DURATION,
) -> List[Cue]:
    words = _words_of(seg)
    if not words:
        return []
    limit = max_chars * max_lines
    groups: List[List[Word]] = []
    cur: List[Word] = []

    def length(ws: List[Word]) -> int:
        return len(" ".join(w.text for w in ws))

    for w in words:
        trial = cur + [w]
        too_long = length(trial) > limit
        too_slow = cur and (w.end - cur[0].start) > max_duration
        if cur and (too_long or too_slow):
            groups.append(cur)
            cur = [w]
        else:
            cur = trial
        # soft break after punctuation once the cue is reasonably filled
        if cur and cur[-1].text.endswith(_PUNCT) and length(cur) >= limit * 0.6:
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)

    cues = [
        Cue(g[0].start, g[-1].end, wrap_lines(" ".join(w.text for w in g), max_chars, max_lines))
        for g in groups
    ]
    return cues


def build_cues(segments: List[Segment], **kw) -> List[Cue]:
    """Split all segments, then enforce monotonic, non-overlapping, positive-length cues."""
    cues: List[Cue] = []
    for seg in segments:
        cues.extend(split_segment(seg, **kw))
    cues.sort(key=lambda c: c.start)
    fixed: List[Cue] = []
    for c in cues:
        start = max(c.start, fixed[-1].end if fixed else 0.0)
        end = max(c.end, start + MIN_DURATION)
        fixed.append(Cue(start, end, c.text))
    # make sure a stretched cue never overlaps its successor
    for i in range(len(fixed) - 1):
        if fixed[i].end > fixed[i + 1].start:
            fixed[i].end = max(fixed[i + 1].start, fixed[i].start + 0.001)
    return [c for c in fixed if c.end > c.start]
