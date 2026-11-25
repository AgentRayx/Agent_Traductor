"""Offline translation with Argos Translate (optional extra: pip install -e .[translate])."""
from __future__ import annotations

import gc
import re
import time
from typing import Dict, List, Set, Tuple

from . import REPO_URL, config
from .logging_setup import log
from .segments import Cue, wrap_lines


class TranslationUnavailable(RuntimeError):
    pass


def _argos():
    try:
        import argostranslate.package as pkg
        import argostranslate.translate as tr
    except ImportError as e:
        if config.FROZEN:
            msg = ("This is the LITE build: it has no translation engine. Download the FULL build "
                   f"({REPO_URL}/releases) or install from PyPI: pip install \"subtitle-forge[translate]\"")
        else:
            msg = "Translation needs the optional extra: pip install -e .[translate]"
        raise TranslationUnavailable(msg) from e
    _stanza_offline()
    return pkg, tr


def _stanza_offline() -> None:
    """Argos builds stanza.Pipeline(...) with the default download method, which phones GitHub for
    'resources_<ver>.json' on EVERY run even though the models ship inside the Argos package.
    Force DownloadMethod.NONE so translation works with no network after the one-time setup."""
    try:
        import stanza
    except ImportError:
        return
    if getattr(stanza.Pipeline, "_subforge_offline", False):
        return
    orig = stanza.Pipeline

    def pipeline(*args, **kwargs):
        kwargs.setdefault("download_method", stanza.DownloadMethod.NONE)
        return orig(*args, **kwargs)

    pipeline._subforge_offline = True
    stanza.Pipeline = pipeline

    try:
        from argostranslate import sbd as _sbd

        _orig_split = _sbd.StanzaSentencizer.split_sentences

        def split_sentences(self, text):
            try:
                return _orig_split(self, text)
            except Exception:
                self.stanza_pipeline = None
                log.warning("stanza SBD failed; falling back to regex sentence split")
                return [s for s in _SENT.split(text) if s.strip()] or [text]

        _sbd.StanzaSentencizer.split_sentences = split_sentences
    except Exception:
        pass


def ensure_pair(src: str, dst: str) -> None:
    """Install the src->dst language package if missing (one-time download into .data)."""
    pkg, tr = _argos()
    if any(l.code == src for l in tr.get_installed_languages()):
        langs = {l.code: l for l in tr.get_installed_languages()}
        if dst in langs and langs[src].get_translation(langs[dst]):
            return
    log.info("Downloading Argos model %s->%s (one-time, stored under %s)", src, dst, config.DATA)
    pkg.update_package_index()
    cand = [p for p in pkg.get_available_packages() if p.from_code == src and p.to_code == dst]
    if not cand:
        raise TranslationUnavailable(
            f"No Argos package for {src}->{dst} in the index. (The pivot via English is applied "
            "automatically by translate_texts/translate_cues; this pair is simply not offered.)"
        )
    pkg.install_from_path(cand[0].download())


PIVOT = "en"
_ROUTES: Dict[Tuple[str, str], List[Tuple[str, str]]] = {}


def _installed_pairs() -> Set[Tuple[str, str]]:
    _, tr = _argos()
    langs = tr.get_installed_languages()
    return {(a.code, b.code) for a in langs for b in langs if a is not b and a.get_translation(b)}


def _remote_pairs() -> Set[Tuple[str, str]]:
    """Pairs in the Argos index (needs network once); empty set when offline."""
    pkg, _ = _argos()
    try:
        pkg.update_package_index()
        return {(p.from_code, p.to_code) for p in pkg.get_available_packages()}
    except Exception as e:  # offline: only what is already installed can be used
        log.debug("Argos index unavailable: %s", e)
        return set()


def plan_route(src: str, dst: str) -> List[Tuple[str, str]]:
    """[(src,dst)] if a direct package exists, else the pivot via English [(src,en),(en,dst)]."""
    if (src, dst) in _ROUTES:
        return _ROUTES[(src, dst)]
    have = _installed_pairs()
    remote: Set[Tuple[str, str]] = set()
    if (src, dst) not in have:
        remote = _remote_pairs()
        have = have | remote
    if (src, dst) in have:
        route = [(src, dst)]
    elif PIVOT not in (src, dst) and (src, PIVOT) in have and (PIVOT, dst) in have:
        route = [(src, PIVOT), (PIVOT, dst)]
    else:
        if not remote:
            raise TranslationUnavailable(
                f"The {src}->{dst} package is not installed and the Argos index is unreachable "
                "(offline?). Connect once to download it.")
        near = sorted(f"{a}->{b}" for a, b in have if src in (a, b) or dst in (a, b))
        raise TranslationUnavailable(
            f"No Argos package for {src}->{dst}, and no pivot via English "
            f"({src}->{PIVOT}->{dst}) either. Pairs available involving {src} or {dst}: "
            f"{', '.join(near) or 'none'}")
    _ROUTES[(src, dst)] = route
    return route


def ensure_route(src: str, dst: str) -> List[Tuple[str, str]]:
    route = plan_route(src, dst)
    for a, b in route:
        ensure_pair(a, b)
    if len(route) > 1:
        log.info("pivote %s->%s->%s", src, PIVOT, dst)
    return route


def _translate_route(tr, text: str, route: List[Tuple[str, str]]) -> str:
    for a, b in route:
        text = _translate_robust(tr, text, a, b)
    return text


def translate_texts(texts: List[str], src: str, dst: str) -> List[str]:
    """Translate plain paragraphs (document mode); pivots through English when needed."""
    if src == dst:
        return list(texts)
    route = ensure_route(src, dst)
    _, tr = _argos()
    return [_translate_route(tr, t, route) for t in texts]


_SENT = re.compile(r"(?<=[.!?])\s+")


def _chunks(text: str, limit: int = 500) -> List[str]:
    """Split long paragraphs on sentence boundaries to keep peak memory low."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for s in _SENT.split(text):
        if cur and len(cur) + len(s) + 1 > limit:
            out.append(cur)
            cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        out.append(cur)
    return out


def _translate_robust(tr, text: str, src: str, dst: str, retries: int = 3) -> str:
    """Low-RAM machines can hit transient allocation failures: free memory and retry."""
    parts = []
    for chunk in _chunks(text):
        for attempt in range(retries):
            try:
                parts.append(tr.translate(chunk, src, dst))
                break
            except (MemoryError, RuntimeError) as e:
                if attempt == retries - 1:
                    raise
                log.debug("translation retry %d after: %s", attempt + 1, e)
                gc.collect()
                time.sleep(2 * (attempt + 1))
    return " ".join(parts)


def translate_cues(cues: List[Cue], src: str, dst: str) -> List[Cue]:
    if src == dst:
        return cues
    route = ensure_route(src, dst)
    _, tr = _argos()
    out = []
    for c in cues:
        text = _translate_route(tr, c.text.replace("\n", " "), route)
        out.append(Cue(c.start, c.end, wrap_lines(text)))
    return out
