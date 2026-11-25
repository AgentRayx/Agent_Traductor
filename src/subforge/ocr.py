"""OCR for scanned PDFs: tesseract (external program, CPU only) via pytesseract."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Optional, Tuple

from . import config  # noqa: F401
from .logging_setup import log

DPI = 150
LOCAL_DIRS = [config.BUNDLED_BIN / "tesseract", config.BIN / "tesseract"]

INSTALL_HELP = (
    "Tesseract OCR is not installed (it is a separate program, not a pip package).\n"
    "  Windows: winget install UB-Mannheim.TesseractOCR   (installs on C:)\n"
    "           or extract it into <project>\\bin\\tesseract\\ (keeps everything on one drive)\n"
    "  Linux:   sudo apt install tesseract-ocr            (+ tesseract-ocr-spa, etc. for other languages)\n"
    "  Any OS:  set SUBFORGE_TESSERACT to the full path of the tesseract executable.\n"
    "Then: pip install -e .[ocr]"
)


class TesseractMissing(RuntimeError):
    pass


def find_tesseract() -> Optional[Path]:
    cands: List[Path] = []
    env = os.environ.get("SUBFORGE_TESSERACT")
    if env:
        cands.append(Path(env))
    for d in LOCAL_DIRS:
        cands += [d / "tesseract.exe", d / "tesseract"]
    found = shutil.which("tesseract")
    if found:
        cands.append(Path(found))
    for pf in ("ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(pf)
        if base:
            cands.append(Path(base) / "Tesseract-OCR" / "tesseract.exe")
    for c in cands:
        if c.is_file():
            return c
    return None


def _setup(lang: str):
    """Return the configured pytesseract module or raise TesseractMissing."""
    exe = find_tesseract()
    if exe is None:
        raise TesseractMissing(INSTALL_HELP)
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise TesseractMissing("pytesseract/Pillow are not installed. Run: pip install -e .[ocr]\n"
                               + INSTALL_HELP) from e
    pytesseract.pytesseract.tesseract_cmd = str(exe)
    tessdata = exe.parent / "tessdata"
    if tessdata.is_dir() and "TESSDATA_PREFIX" not in os.environ:
        os.environ["TESSDATA_PREFIX"] = str(tessdata)
    return pytesseract


def available() -> bool:
    try:
        _setup("eng")
        return True
    except TesseractMissing:
        return False


def ocr_page(page, lang: str = "eng") -> List[Tuple[Tuple[float, float, float, float], str]]:
    """OCR one pymupdf page at 150 dpi. Returns [(rect in PDF points, text)] per paragraph."""
    pt = _setup(lang)
    from PIL import Image

    pix = page.get_pixmap(dpi=DPI)
    img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    del pix
    try:
        data = pt.image_to_data(img, lang=lang, output_type=pt.Output.DICT)
    except pt.TesseractError as e:
        raise RuntimeError(f"tesseract failed (language '{lang}' installed?): {e}") from e
    finally:
        img.close()
    scale = 72.0 / DPI
    paras = {}
    for i, word in enumerate(data["text"]):
        word = (word or "").strip()
        if not word or float(data["conf"][i]) < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i])
        x, y, w, h = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        p = paras.setdefault(key, {"words": [], "box": [x, y, x + w, y + h]})
        p["words"].append(word)
        b = p["box"]
        b[0], b[1], b[2], b[3] = min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)
    out = []
    for p in paras.values():
        x0, y0, x1, y1 = (v * scale for v in p["box"])
        out.append(((x0, y0, x1, y1), " ".join(p["words"])))
    log.debug("ocr: %d paragraphs", len(out))
    return sorted(out, key=lambda r: (round(r[0][1]), r[0][0]))
