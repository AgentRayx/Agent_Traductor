"""Tiny dependency-free language detector (stop-word voting) for document mode."""
import re
from typing import Optional

_STOP = {
    "en": "the of and to in is that it for with as was on are this be by at from or have not but an they which you were their has had".split(),
    "es": "el la de que y en los las del se por un una con no es para su al lo como más pero sus le ya o este sí porque esta entre cuando muy sin sobre".split(),
    "fr": "le la les de des du et en un une que qui dans pour pas sur au avec ce il est ne se son sa ses plus par nous vous mais ou".split(),
    "de": "der die das und in den von zu mit sich des auf für ist im dem nicht ein eine als auch es an werden aus er hat dass sie nach wird bei".split(),
    "it": "il lo la i gli le di che e in un una per con non è si da come al del della dei più ma sono anche questo nel alla suo".split(),
    "pt": "o a os as de que e do da em um uma para com não é se por mais dos como mas foi ao ele das tem à seu sua ou ser quando muito".split(),
}


def detect_language(text: str) -> str:
    words = re.findall(r"[^\W\d_]+", text.lower())[:4000]
    if len(words) < 8:
        raise ValueError("not enough text to detect the language; pass --lang")
    scores = {lang: sum(1 for w in words if w in set(sw)) for lang, sw in _STOP.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (best, s1), (_, s2) = ranked[0], ranked[1]
    if s1 < 3 or s1 < 1.2 * s2:
        raise ValueError("could not detect the document language reliably; pass --lang")
    return best


_SETS = {lang: frozenset(sw) for lang, sw in _STOP.items()}


def detect_block(text: str, strict: bool = False) -> Optional[str]:
    """Best-effort language of ONE paragraph; None when it is too short/ambiguous to tell.
    The detector is deterministic (no random seed); `strict` demands more evidence, for re-checks."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    if len(words) < 4:
        return None
    scores = sorted(((sum(1 for w in words if w in sw), lang) for lang, sw in _SETS.items()), reverse=True)
    (s1, best), (s2, _) = scores[0], scores[1]
    if s1 < (3 if strict else 2) or s1 < (2.0 if strict else 1.5) * s2:
        return None
    return best
