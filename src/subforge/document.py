"""Document mode: PDF -> translated bilingual/clean PDF, EPUB or Markdown (offline)."""
from __future__ import annotations

import gc
import html
import re
import uuid
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import config  # noqa: F401
from .langdetect import detect_block, detect_language
from .logging_setup import log

FORMATS = ("pdf-bilingual", "pdf-clean", "epub", "md")


class ScannedPDF(RuntimeError):
    pass


class NoText(RuntimeError):
    pass


class MixedLanguage(ValueError):
    """The document is partly in the target language: --mixed is the right mode."""


@dataclass
class Block:
    page: int  # 0-based index in the ORIGINAL pdf
    rect: Tuple[float, float, float, float]
    text: str
    translated: str = ""
    keep: bool = False  # leave untouched (emails, URLs...): not translated, not re-rendered
    lang: Optional[str] = None  # per-block language (mixed mode)


# Things that must survive translation verbatim: URLs, e-mails, DOIs, arXiv ids.
_PROTECT = re.compile(
    r"(?:https?://|www\.)[^\s<>\"']+"          # URLs
    r"|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"           # e-mails
    r"|(?:doi|arxiv):\s*[^\s,;]+", re.I)
_TOKEN = re.compile(r"SFURL(\d+)", re.I)
_TRAIL = ".,;:!?)]}"


def _protected_spans(text: str):
    """(start, end) of each protected item; trailing sentence punctuation is not part of it."""
    for m in _PROTECT.finditer(text):
        end = m.end()
        while end > m.start() and text[end - 1] in _TRAIL:
            end -= 1
        yield m.start(), end


def is_only_protected(text: str) -> bool:
    """True when the block is just URLs/e-mails/ids with no prose around them."""
    spans = list(_protected_spans(text))
    if not spans:
        return False
    rest, last = [], 0
    for a, b in spans:
        rest.append(text[last:a])
        last = b
    rest.append(text[last:])
    return not _translatable(" ".join(rest).strip())


def mask(text: str):
    """Swap each protected item for a unique token the translator will leave alone."""
    found: List[str] = []
    out, last = [], 0
    for a, b in _protected_spans(text):
        out.append(text[last:a])
        out.append(f"SFURL{len(found)}")
        found.append(text[a:b])
        last = b
    out.append(text[last:])
    return "".join(out), found


def unmask(text: str, found: List[str]) -> str:
    if not found:
        return text
    seen = set()

    def back(m):
        i = int(m.group(1))
        if i < len(found):
            seen.add(i)
            return found[i]
        return m.group(0)

    text = _TOKEN.sub(back, text)
    missing = [f for i, f in enumerate(found) if i not in seen]  # engine dropped it: never lose a URL
    return f"{text} {' '.join(missing)}" if missing else text


def translate_protected(texts: List[str], src: str, dst: str) -> List[str]:
    """translate_texts() with URLs/e-mails/DOIs masked so only the prose is translated."""
    from .translate import translate_texts

    masked = [mask(t) for t in texts]
    done = translate_texts([m for m, _ in masked], src, dst)
    return [unmask(t, f) for t, (_, f) in zip(done, masked)]


def _fitz():
    try:
        import pymupdf
        return pymupdf
    except ImportError as e:  # pragma: no cover
        raise RuntimeError("pymupdf is not installed. Run: pip install -e .") from e


def parse_pages(spec: Optional[str], count: int) -> List[int]:
    """'1-3,5' (1-based) -> [0,1,2,4]. None -> all pages."""
    if not spec:
        return list(range(count))
    out = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        a, _, b = part.partition("-")
        try:
            lo, hi = int(a), int(b or a)
        except ValueError:
            raise ValueError(f"invalid --pages value: {spec!r} (example: 1-3,5)")
        if lo < 1 or hi < lo or hi > count:
            raise ValueError(f"--pages {part!r} is outside 1-{count}")
        out.update(range(lo - 1, hi))
    return sorted(out)


def clean_text(t: str) -> str:
    t = re.sub(r"(?<=\w)[-­]\n(?=[a-zà-ÿ])", "", t)  # de-hyphenate line breaks
    return re.sub(r"\s+", " ", t).strip()


def _translatable(t: str) -> bool:
    return len(t) >= 3 and re.search(r"[^\W\d_]{2}", t) is not None


def extract_blocks(path: Path, pages: Optional[str] = None, ocr: bool = False,
                   ocr_lang: str = "eng") -> Tuple[List[Block], List[int]]:
    fm = _fitz()
    with fm.open(str(path)) as doc:
        idx = parse_pages(pages, doc.page_count)
        if ocr:  # fail early with install instructions, before any work
            from . import ocr as _ocr
            _ocr._setup(ocr_lang)
        blocks: List[Block] = []
        text_pages = image_pages = 0
        for i in idx:
            page = doc[i]
            chars = 0
            for x0, y0, x1, y1, txt, _n, btype in page.get_text("blocks", sort=True):
                if btype != 0:
                    continue
                t = clean_text(txt)
                if _translatable(t):
                    blocks.append(Block(i, (x0, y0, x1, y1), t, keep=is_only_protected(t)))
                    chars += len(t)
            if chars >= 20:
                text_pages += 1
            elif page.get_images():
                if ocr:  # one page at a time (RAM)
                    log.info("OCR page %d/%d", i + 1, doc.page_count)
                    for rect, txt in _ocr.ocr_page(page, ocr_lang):
                        t = clean_text(txt)
                        if _translatable(t):
                            blocks.append(Block(i, rect, t, keep=is_only_protected(t)))
                            chars += len(t)
                    if chars >= 20:
                        text_pages += 1
                else:
                    image_pages += 1
    if idx and image_pages and text_pages / len(idx) < 0.2:
        raise ScannedPDF(
            "This PDF has no selectable text (its pages are scanned images). "
            "Use --ocr to run OCR on it (needs tesseract; see README)."
        )
    if not blocks:
        raise NoText("No extractable text found in the selected pages.")
    return blocks, idx


# ------------------------------------------------------------------ rendering
_CSS = "* {font-family: sans-serif; font-size: 9pt; line-height: 1.2;} .o {color: #808080;} p {margin: 0 0 2pt 0;}"
_PH_CSS = "* {font-family: sans-serif; font-size: 6pt; color: #a00000;} p {margin: 0;}"
PLACEHOLDER = "[bloque no renderizable: ver MD/EPUB]"
_MARGIN = 12.0      # minimum distance from the page edge
_MIN_SCALE = 0.7    # never shrink text below 70% of 9pt (~6.3pt): below that it is not legible
_MIN_H = 8.0        # a box shorter than one scaled line cannot hold text


def _overlaps(a, b, tol: float = 1.0) -> bool:
    return min(a.x1, b.x1) - max(a.x0, b.x0) > tol and min(a.y1, b.y1) - max(a.y0, b.y0) > tol


def _room_for(b: Block, page_blocks: List[Block], page_rect):
    """The block's own rect, grown downwards into free space (never past the next block below)."""
    fm = _fitz()
    x0, y0, x1, y1 = b.rect
    x0, x1 = max(x0, _MARGIN), min(x1, page_rect.x1 - _MARGIN)
    limit = page_rect.y1 - _MARGIN
    for o in page_blocks:
        if o is b:
            continue
        if min(x1, o.rect[2]) - max(x0, o.rect[0]) > 1 and y1 - 2 <= o.rect[1] < limit:
            limit = o.rect[1] - 1
    return fm.Rect(x0, y0, x1, max(y1, limit))


def _resolve(rect, obstacles):
    """Shrink/move `rect` so it does not overlap anything already on the page."""
    for _ in range(len(obstacles) + 1):
        hit = next((o for o in obstacles if _overlaps(rect, o)), None)
        if hit is None:
            break
        if hit.y0 <= rect.y0 + 0.5:  # obstacle covers our top edge: start below it
            rect.y0 = hit.y1 + 1
        else:                        # obstacle is further down: stop above it
            rect.y1 = hit.y0 - 1
        if rect.y1 - rect.y0 < 1:
            break
    return rect


def _render_pdf(src: Path, blocks: List[Block], idx: List[int], out: Path, bilingual: bool) -> int:
    """Returns how many blocks could not be rendered legibly (replaced by a placeholder)."""
    fm = _fitz()
    doc = fm.open(str(src))
    placeholders = 0
    try:
        doc.select(idx)
        pos = {orig: i for i, orig in enumerate(idx)}
        all_by_page: Dict[int, List[Block]] = defaultdict(list)
        for b in blocks:
            all_by_page[pos[b.page]].append(b)
        for pno, allb in all_by_page.items():
            page = doc[pno]
            bl = [b for b in allb if not b.keep]
            if not bl:
                continue
            for b in bl:
                page.add_redact_annot(fm.Rect(b.rect), fill=False)
            page.apply_redactions(images=fm.PDF_REDACT_IMAGE_NONE)  # keep pictures untouched
            # untouched text stays where it is: it is an obstacle like anything we place
            taken = [fm.Rect(b.rect) for b in allb if b.keep]
            for b in sorted(bl, key=lambda x: (round(x.rect[1]), x.rect[0])):
                rect = _resolve(_room_for(b, allb, page.rect), taken)
                body = f"<p>{html.escape(b.translated)}</p>"
                if bilingual:
                    body = f'<p class="o">{html.escape(b.text)}</p>' + body
                used = None
                if rect.y1 - rect.y0 >= _MIN_H and rect.x1 - rect.x0 >= 20:
                    spare, _scale = page.insert_htmlbox(rect, body, css=_CSS, scale_low=_MIN_SCALE)
                    if spare >= 0:
                        used = fm.Rect(rect.x0, rect.y0, rect.x1, max(rect.y1 - spare, rect.y0 + 1))
                if used is None:
                    placeholders += 1
                    log.debug("page %d: block %s not legible, placeholder", pno + 1, b.rect)
                    ph = fm.Rect(rect.x0, rect.y0, max(rect.x1, rect.x0 + 120), max(rect.y1, rect.y0 + _MIN_H))
                    ph.x1 = min(ph.x1, page.rect.x1 - _MARGIN)
                    ph = _resolve(ph, taken)
                    if ph.y1 - ph.y0 < _MIN_H:  # no free space at all: take a thin strip anyway
                        ph.y1 = ph.y0 + _MIN_H
                    page.insert_htmlbox(ph, f"<p>{PLACEHOLDER}</p>", css=_PH_CSS, scale_low=0)
                    used = ph
                taken.append(used)
        doc.save(str(out), garbage=3, deflate=True)
    finally:
        doc.close()
    return placeholders


def _pages_of(blocks: List[Block]) -> Dict[int, List[Block]]:
    d: Dict[int, List[Block]] = defaultdict(list)
    for b in blocks:
        d[b.page].append(b)
    return dict(sorted(d.items()))


def _render_md(title: str, blocks: List[Block], out: Path, translated: bool) -> None:
    parts = [f"# {title}\n"]
    for p, bl in _pages_of(blocks).items():
        parts.append(f"\n## Page {p + 1}\n")
        for b in bl:
            if translated and b.translated != b.text:
                parts.append(f"> {b.text}\n\n{b.translated}\n")
            else:
                parts.append(f"{b.text}\n")
    out.write_text("\n".join(parts), encoding="utf-8", newline="\n")


def _render_epub(title: str, blocks: List[Block], out: Path, lang: str, translated: bool) -> None:
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier(f"subforge-{uuid.uuid4()}")
    book.set_title(title)
    book.set_language(lang)
    chapters = []
    for p, bl in _pages_of(blocks).items():
        c = epub.EpubHtml(title=f"Page {p + 1}", file_name=f"page_{p + 1:04d}.xhtml", lang=lang)
        inner = []
        for b in bl:
            if translated and b.translated != b.text:
                inner.append(f'<p style="color:#808080"><em>{html.escape(b.text)}</em></p>')
                inner.append(f"<p>{html.escape(b.translated)}</p>")
            else:
                inner.append(f"<p>{html.escape(b.text)}</p>")
        c.set_content(f"<h2>Page {p + 1}</h2>" + "".join(inner))
        book.add_item(c)
        chapters.append(c)
    book.toc = tuple(chapters)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + chapters
    epub.write_epub(str(out), book)


# ------------------------------------------------------------------ mixed-language support
MIXED_LOW, MIXED_HIGH = 0.20, 0.80


def classify_blocks(blocks: List[Block]) -> None:
    """Set Block.lang per paragraph. Short/ambiguous ones (headings, names) inherit the language
    of their neighbours when the previous and next classified blocks agree."""
    for b in blocks:
        b.lang = detect_block(b.text)
    known = [i for i, b in enumerate(blocks) if b.lang]
    for i, b in enumerate(blocks):
        if b.lang:
            continue
        prev = next((blocks[j].lang for j in reversed(known) if j < i), None)
        nxt = next((blocks[j].lang for j in known if j > i), None)
        if prev and prev == nxt:
            b.lang = prev


def target_share(blocks: List[Block], target: str) -> Optional[float]:
    """Fraction of the (classified) words that are already in `target`; None if unknown."""
    tot = tgt = 0
    for b in blocks:
        if b.keep or not b.lang:
            continue
        n = len(b.text.split())
        tot += n
        if b.lang == target:
            tgt += n
    return tgt / tot if tot else None


def _dominant_language(blocks: List[Block]) -> Optional[str]:
    words: Dict[str, int] = defaultdict(int)
    for b in blocks:
        if b.lang:
            words[b.lang] += len(b.text.split())
    return max(words, key=words.get) if words else None


def _translate_mixed(blocks: List[Block], target: str, lang: str, notes: List[str]) -> int:
    """Translate only the blocks not already in `target`. Returns how many were translated."""
    todo = [b for b in blocks if not b.keep and b.lang != target]
    for b in blocks:  # target-language (and kept) blocks pass through untouched
        if b.keep or b.lang == target:
            b.keep = True
            b.translated = b.text
    if not todo:
        raise ValueError(f"the document is already in '{target}': nothing to translate")
    # a minority 'fr' block in a mostly-'es' document may be a detector false positive
    # (short texts): re-check with stricter evidence; translate anyway (pivot covers it) but report
    dominant = _dominant_language(blocks)
    for b in list(todo):
        if b.lang and dominant and b.lang != dominant:
            again = detect_block(b.text, strict=True)
            if again == dominant:  # second opinion says it IS the dominant language
                b.lang = dominant
                if dominant == target:
                    b.keep, b.translated = True, b.text
                    todo.remove(b)
            elif again != b.lang:
                notes.append(f"página {b.page + 1}: bloque detectado como '{b.lang}' en un documento "
                             f"mayormente '{dominant}' (detección dudosa), se tradujo igual: "
                             f"«{b.text[:50]}…» / page {b.page + 1}: low-confidence '{b.lang}' block, "
                             "translated anyway")
    if not todo:
        raise ValueError(f"the document is already in '{target}': nothing to translate")
    fallback = lang if lang != "auto" else None
    if fallback is None:
        found = [b.lang for b in todo if b.lang]
        if found:
            fallback = max(set(found), key=found.count)
        else:
            try:
                fallback = detect_language(" ".join(b.text for b in todo))
            except ValueError:
                raise ValueError("could not detect the language of the non-%s text; pass --lang" % target)
    groups: Dict[str, List[Block]] = defaultdict(list)
    for b in todo:
        groups[b.lang or fallback].append(b)
    for src_l, grp in groups.items():
        for b, t in zip(grp, translate_protected([x.text for x in grp], src_l, target)):
            b.translated = t
        gc.collect()  # free the previous language pair's models before loading the next
    log.info("mixed mode: %d blocks translated, %d left untouched (already '%s' or kept)",
             len(todo), len(blocks) - len(todo), target)
    return len(todo)


# ------------------------------------------------------------------ entry point
def convert(src: Path, out_dir: Path, translate: Optional[str] = None, fmt: Optional[str] = None,
            lang: str = "auto", pages: Optional[str] = None, ocr: bool = False,
            ocr_lang: str = "eng", mixed: bool = False, notes: Optional[List[str]] = None) -> Path:
    """`notes` (optional) collects user-facing remarks (auto mixed mode, unrenderable blocks)."""
    from .cli import unique_path

    notes = notes if notes is not None else []
    fmt = fmt or ("pdf-bilingual" if translate else "md")
    if fmt not in FORMATS:
        raise ValueError(f"unknown format {fmt!r}; choose one of {', '.join(FORMATS)}")
    if fmt.startswith("pdf") and not translate:
        raise ValueError(f"--format {fmt} needs --translate LANG")
    if src.suffix.lower() != ".pdf":
        raise ValueError("only PDF input is supported in document mode")
    if mixed and not translate:
        raise ValueError("--mixed needs --translate LANG")

    blocks, idx = extract_blocks(src, pages, ocr, ocr_lang)
    log.info("[%s] %d text blocks on %d pages", src.name, len(blocks), len(idx))

    src_lang = lang
    if translate:
        if mixed or lang == "auto":
            classify_blocks(blocks)
        share = target_share(blocks, translate)
        if not mixed and share is not None and lang == "auto":
            pct = round(share * 100)
            if share > MIXED_HIGH:
                mixed = True
                msg = (f"ya está mayormente en '{translate}' ({pct}%): se traducirán solo los bloques "
                       f"en otros idiomas / already mostly in '{translate}' ({pct}%): only blocks in "
                       "other languages will be translated")
                log.warning(msg)
                notes.append(msg)
            elif share >= MIXED_LOW:
                raise MixedLanguage(
                    f"the document is mixed: {pct}% is already in '{translate}'. Use --mixed (CLI) or "
                    "tick «traducir solo lo que no esté en el idioma destino» (UI) to translate only "
                    f"the blocks in other languages / el documento es de idioma mixto ({pct}% ya "
                    f"está en '{translate}')")
        if mixed:
            _translate_mixed(blocks, translate, lang, notes)
            src_lang = lang
        else:
            if lang == "auto":
                src_lang = detect_language(" ".join(b.text for b in blocks))
                log.info("detected language: %s", src_lang)
            if src_lang == translate:
                raise ValueError(f"the document is already in '{translate}'")
            todo = [b for b in blocks if not b.keep]
            for b, t in zip(todo, translate_protected([b.text for b in todo], src_lang, translate)):
                b.translated = t
            for b in blocks:
                if b.keep:
                    b.translated = b.text

    tag = translate or "text"
    out_dir.mkdir(parents=True, exist_ok=True)
    if fmt in ("pdf-bilingual", "pdf-clean"):
        bi = fmt == "pdf-bilingual"
        out = unique_path(out_dir / (f"{src.stem}.{tag}.bilingual.pdf" if bi else f"{src.stem}.{tag}.pdf"))
        bad = _render_pdf(src, blocks, idx, out, bilingual=bi)
        if bad:
            msg = (f"{bad} bloque(s) no caben de forma legible y se marcaron con «{PLACEHOLDER}» / "
                   f"{bad} block(s) did not fit legibly: use the MD or EPUB output")
            log.warning(msg)
            notes.append(msg)
    elif fmt == "epub":
        out = unique_path(out_dir / f"{src.stem}.{tag}.epub")
        _render_epub(src.stem, blocks, out, translate or (src_lang if src_lang != "auto" else "und"), bool(translate))
    else:
        out = unique_path(out_dir / f"{src.stem}.{tag}.md")
        _render_md(src.stem, blocks, out, bool(translate))
    log.info("wrote %s", out)
    return out
