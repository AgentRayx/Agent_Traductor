import re
import zipfile

import pymupdf
import pytest

from subforge import document
from subforge.document import NoText, ScannedPDF, convert, extract_blocks, parse_pages
from subforge.langdetect import detect_language

P1 = ("The history of the printing press is a story of how knowledge was shared with the world. "
      "It was invented in the fifteenth century and it changed the way that people read.")
P2 = ("In this chapter we describe the main parts of the machine, and we explain how they work "
      "together to produce a page of text.")
P3 = "Another page has a short paragraph that is also written in plain English for the test."


def fake_translate_texts(texts, src, dst):
    return [f"[{dst}] {t}" for t in texts]


@pytest.fixture(autouse=True)
def fake_translator(monkeypatch):
    monkeypatch.setattr("subforge.translate.translate_texts", fake_translate_texts)


@pytest.fixture
def pdf(tmp_path):
    path = tmp_path / "book.pdf"
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 500, 130), P1, fontsize=11)
    p.insert_textbox(pymupdf.Rect(50, 200, 500, 280), P2, fontsize=11)
    p.draw_rect(pymupdf.Rect(50, 400, 200, 450), fill=(0.8, 0.9, 1))  # graphic must survive
    p2 = doc.new_page()
    p2.insert_textbox(pymupdf.Rect(50, 50, 500, 130), P3, fontsize=11)
    doc.save(path)
    return path


def test_parse_pages():
    assert parse_pages(None, 3) == [0, 1, 2]
    assert parse_pages("1-2,3", 5) == [0, 1, 2]
    with pytest.raises(ValueError):
        parse_pages("9", 3)


def test_extract_paragraphs(pdf):
    blocks, idx = extract_blocks(pdf)
    texts = [b.text for b in blocks]
    assert idx == [0, 1]
    assert len(blocks) == 3
    assert texts[0].startswith("The history of the printing press") and "\n" not in texts[0]
    assert [b.page for b in blocks] == [0, 0, 1]


def test_detect_language():
    assert detect_language(P1 + " " + P2) == "en"
    es = ("El libro es una obra que se publicó en la ciudad y que los lectores de todo el mundo "
          "han leído con mucho interés porque trata de la historia de las personas y de su tierra.")
    assert detect_language(es) == "es"


def test_markdown_bilingual(pdf, tmp_path):
    out = convert(pdf, tmp_path / "o", translate="es", fmt="md")
    text = out.read_text(encoding="utf-8")
    assert out.name == "book.es.md" and "## Page 1" in text and "## Page 2" in text
    assert f"> {P3}" in text and f"[es] {P3}" in text


def test_markdown_without_translation(pdf, tmp_path):
    out = convert(pdf, tmp_path / "o")
    assert out.suffix == ".md" and "[es]" not in out.read_text(encoding="utf-8")


def test_epub(pdf, tmp_path):
    out = convert(pdf, tmp_path / "o", translate="es", fmt="epub")
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "mimetype" in names and any(n.endswith("page_0001.xhtml") for n in names)
        body = z.read(next(n for n in names if n.endswith("page_0002.xhtml"))).decode("utf-8")
    assert f"[es] {P3}" in body


def test_pdf_bilingual_keeps_page_and_graphics(pdf, tmp_path):
    out = convert(pdf, tmp_path / "o", translate="es", fmt="pdf-bilingual")
    with pymupdf.open(out) as d:
        assert d.page_count == 2
        text = d[0].get_text()
        assert "[es]" in text and "printing press" in text  # translation + original both present
        assert len(d[0].get_drawings()) >= 1  # vector graphic untouched
        gray = [s for b in d[0].get_text("dict")["blocks"] for l in b.get("lines", [])
                for s in l["spans"] if s["color"] != 0 and "printing" in s["text"]]
        assert gray, "original text should be rendered in gray"


def test_emails_and_urls_are_left_untouched(tmp_path):
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 500, 130), P1, fontsize=11)
    p.insert_textbox(pymupdf.Rect(50, 200, 400, 240), "jane.doe@example.com", fontsize=11)
    path = tmp_path / "mail.pdf"
    doc.save(path)
    out = convert(path, tmp_path / "o", translate="es", fmt="pdf-bilingual")
    with pymupdf.open(out) as d:
        t = d[0].get_text()
    assert t.count("jane.doe@example.com") == 1 and "[es] jane" not in t and "[es] The history" in t


def test_pdf_clean_only_translation(pdf, tmp_path):
    out = convert(pdf, tmp_path / "o", translate="es", fmt="pdf-clean", pages="2")
    with pymupdf.open(out) as d:
        assert d.page_count == 1
        t = d[0].get_text()
    assert "[es]" in t and t.count("Another page") == 1


def test_pdf_formats_require_translate(pdf, tmp_path):
    with pytest.raises(ValueError):
        convert(pdf, tmp_path / "o", fmt="pdf-clean")


def test_same_language_rejected(pdf, tmp_path):
    with pytest.raises(ValueError):
        convert(pdf, tmp_path / "o", translate="en", fmt="md")


def test_scanned_pdf_detected(tmp_path):
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 200), False)
    pix.set_rect(pix.irect, (200, 200, 200))
    doc = pymupdf.open()
    for _ in range(2):
        doc.new_page().insert_image(pymupdf.Rect(0, 0, 300, 300), pixmap=pix)
    path = tmp_path / "scan.pdf"
    doc.save(path)
    with pytest.raises(ScannedPDF) as e:
        extract_blocks(path)
    assert "OCR" in str(e.value)


def test_empty_pdf_no_text(tmp_path):
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "blank.pdf"
    doc.save(path)
    with pytest.raises(NoText):
        extract_blocks(path)


# ------------------------------------------------------------------ mixed-language documents
ES1 = ("El libro es una obra que se publicó en la ciudad y que los lectores de todo el mundo "
       "han leído con mucho interés porque trata de la historia de las personas.")
ES2 = ("Este es el segundo párrafo del documento, que también está escrito en español y que no "
       "debe ser traducido por el programa.")


def _mixed_pdf(tmp_path, texts, name="mixed.pdf"):
    doc = pymupdf.open()
    p = doc.new_page()
    y = 50
    for t in texts:
        p.insert_textbox(pymupdf.Rect(50, y, 500, y + 70), t, fontsize=11)
        y += 100
    path = tmp_path / name
    doc.save(path)
    return path


def test_detect_block():
    from subforge.langdetect import detect_block
    assert detect_block(ES1) == "es" and detect_block(P1) == "en"
    assert detect_block("Capítulo 1") is None  # too short to tell


def test_mixed_translates_only_foreign_blocks(tmp_path):
    path = _mixed_pdf(tmp_path, [ES1, P1, ES2, P2])
    out = convert(path, tmp_path / "o", translate="es", fmt="md", mixed=True)
    text = out.read_text(encoding="utf-8")
    assert f"[es] {P1}" in text and f"[es] {P2}" in text
    assert "[es] El libro" not in text and "[es] Este es" not in text
    assert text.count("El libro es una obra") == 1  # not duplicated as quote + translation


def test_mixed_pdf_leaves_spanish_blocks_intact(tmp_path):
    path = _mixed_pdf(tmp_path, [ES1, P1, ES2, P2])
    out = convert(path, tmp_path / "o", translate="es", fmt="pdf-clean", mixed=True)
    with pymupdf.open(out) as d:
        t = " ".join(d[0].get_text().split())
    assert "El libro es una obra" in t and "[es] The history" in t and "[es] El libro" not in t


def test_mixed_suggested_for_20_to_80_percent(tmp_path):
    path = _mixed_pdf(tmp_path, [ES1, P1, ES2, P2])
    with pytest.raises(document.MixedLanguage) as e:
        convert(path, tmp_path / "o", translate="es", fmt="md")
    assert "--mixed" in str(e.value)


def test_mostly_target_language_auto_mixed_with_warning(tmp_path):
    path = _mixed_pdf(tmp_path, [ES1, ES2, ES1, ES2, ES1, ES2, P3])
    notes = []
    out = convert(path, tmp_path / "o", translate="es", fmt="md", notes=notes)
    text = out.read_text(encoding="utf-8")
    assert f"[es] {P3}" in text and "[es] El libro" not in text
    assert notes and "mayormente" in notes[0]


def test_below_20_percent_is_normal_mode(tmp_path):
    path = _mixed_pdf(tmp_path, [P1, P2, P3, P1, P2, ES2])
    out = convert(path, tmp_path / "o", translate="es", fmt="md")
    assert "[es] Este es el segundo" in out.read_text(encoding="utf-8")  # whole doc translated


def test_mixed_flag_requires_translate(pdf, tmp_path):
    with pytest.raises(ValueError):
        convert(pdf, tmp_path / "o", mixed=True)


def test_mixed_cli_flag():
    from subforge.cli import build_parser
    assert build_parser().parse_args(["doc", "x.pdf", "--translate", "es", "--mixed"]).mixed is True


# ------------------------------------------------------------------ PDF layout quality
def _line_boxes(page):
    return [pymupdf.Rect(l["bbox"]) for b in page.get_text("dict")["blocks"] for l in b.get("lines", [])]


def _assert_no_overlap(page):
    boxes = _line_boxes(page)
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            ix = min(a.x1, b.x1) - max(a.x0, b.x0)
            iy = min(a.y1, b.y1) - max(a.y0, b.y0)
            assert not (ix > 1 and iy > 2), f"text overlaps: {a} / {b}"


def _render(tmp_path, rects_texts, keep=()):
    """Render hand-made blocks (so their rects can overlap on purpose) on a blank page."""
    doc = pymupdf.open()
    pg = doc.new_page()
    for i in keep:  # untouched blocks are real text in the source page
        pg.insert_textbox(pymupdf.Rect(rects_texts[i][0]), rects_texts[i][1], fontsize=9)
    src = tmp_path / "blank.pdf"
    doc.save(src)
    blocks = [document.Block(0, r, t, f"[es] {t}") for r, t in rects_texts]
    for i in keep:
        blocks[i].keep, blocks[i].translated = True, blocks[i].text
    out = tmp_path / "out.pdf"
    bad = document._render_pdf(src, blocks, [0], out, bilingual=True)
    return out, bad


def test_pdf_bilingual_never_overlaps_text(tmp_path):
    # B starts inside A, C starts inside B: the old layout piled all three on top of each other
    out, bad = _render(tmp_path, [((50, 50, 300, 130), P1), ((50, 105, 300, 185), P2),
                                  ((50, 160, 300, 240), P3)])
    with pymupdf.open(out) as d:
        _assert_no_overlap(d[0])
        t = " ".join(d[0].get_text().split())
    assert bad == 0 or document.PLACEHOLDER in t
    assert "[es] In this chapter" in t or document.PLACEHOLDER in t


def test_pdf_layout_respects_untouched_blocks(tmp_path):
    out, _ = _render(tmp_path, [((50, 50, 300, 100), P1), ((50, 110, 300, 160), ES1)], keep=[1])
    with pymupdf.open(out) as d:
        _assert_no_overlap(d[0])
        assert "El libro es una obra" in d[0].get_text()


def test_pdf_text_stays_inside_margins(tmp_path):
    out, _ = _render(tmp_path, [((0, 780, 595, 835), P1)])  # block hanging off the A4 page edge
    with pymupdf.open(out) as d:
        page = d[0]
        for r in _line_boxes(page):
            assert r.x0 >= document._MARGIN - 1 and r.x1 <= page.rect.x1 - document._MARGIN + 1
            assert r.y1 <= page.rect.y1 - document._MARGIN + 1


def test_unfittable_block_gets_placeholder(tmp_path):
    notes = []
    out, bad = _render(tmp_path, [((50, 50, 500, 80), P1), ((50, 82, 130, 92), P2),
                                  ((50, 94, 500, 124), P3)])
    with pymupdf.open(out) as d:
        t = " ".join(d[0].get_text().split())
        _assert_no_overlap(d[0])
    assert bad >= 1 and document.PLACEHOLDER in t


def test_placeholder_reported_in_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(document, "_render_pdf", lambda *a, **k: 2)
    notes = []
    pdf_ = _mixed_pdf(tmp_path, [P1, P2])
    convert(pdf_, tmp_path / "o", translate="es", fmt="pdf-bilingual", notes=notes)
    assert any("no caben" in n for n in notes)


def test_markdown_keeps_everything_for_dense_pdf(tmp_path):
    path = _mixed_pdf(tmp_path, [P1, P2, P3])
    text = convert(path, tmp_path / "o", translate="es", fmt="md").read_text(encoding="utf-8")
    assert all(f"[es] {x}" in text for x in (P1, P2, P3))


def test_ui_marks_recommended_and_experimental():
    from importlib.resources import files
    html = files("subforge").joinpath("static/index.html").read_text(encoding="utf-8")
    assert "EPUB (recomendado)" in html and "Markdown (recomendado)" in html
    assert "(experimental)" in html and 'class="mixed"' in html


# ------------------------------------------------------------------ URL / e-mail masking
NOTE = "Note: If you use www.Youtube.com to make the video, please share the link with your teacher."


def test_mask_unmask_roundtrip():
    t = "See www.Youtube.com, mail jane.doe@example.com or doi: 10.1000/xyz123. Thanks."
    m, found = document.mask(t)
    assert "www" not in m and "@" not in m and found[0] == "www.Youtube.com"  # trailing comma not eaten
    assert document.unmask(m.replace("SFURL", "sfurl"), found) == t  # engine changed the token case
    assert document.unmask("sin tokens", ["http://x.org"]) == "sin tokens http://x.org"  # dropped -> appended


def test_only_urls_and_emails_are_whole_block_keep():
    assert document.is_only_protected("jane.doe@example.com")
    assert document.is_only_protected("https://example.org/a?b=1")
    assert document.is_only_protected("doi: 10.1000/xyz123")
    assert not document.is_only_protected(NOTE)
    assert not document.is_only_protected("Contact: jane.doe@example.com")  # prose around it


def test_block_with_url_is_translated_and_url_survives(tmp_path, monkeypatch):
    seen = []

    def fake(texts, src, dst):  # a hostile engine: lower-cases EVERYTHING it is given
        seen.extend(texts)
        return [f"[{dst}] {t.lower()}" for t in texts]

    monkeypatch.setattr("subforge.translate.translate_texts", fake)
    doc = pymupdf.open()
    doc.new_page().insert_textbox(pymupdf.Rect(50, 50, 500, 130), NOTE, fontsize=11)
    path = tmp_path / "oa.pdf"
    doc.save(path)
    out = convert(path, tmp_path / "o", translate="es", fmt="pdf-clean", lang="en")
    with pymupdf.open(out) as d:
        t = " ".join(d[0].get_text().split())
    assert "[es] note: if you use" in t           # prose WAS translated
    assert "www.Youtube.com" in t                  # URL intact, original case
    assert not any("www" in x or "Youtube" in x for x in seen)  # the engine never saw the URL
    assert "SFURL" not in t.upper()


def test_mixed_mode_also_masks(tmp_path, monkeypatch):
    monkeypatch.setattr("subforge.translate.translate_texts",
                        lambda ts, s, d: [f"[{d}] {t.lower()}" for t in ts])
    path = _mixed_pdf(tmp_path, [ES1, NOTE, ES2])
    text = convert(path, tmp_path / "o", translate="es", fmt="md", mixed=True).read_text(encoding="utf-8")
    assert "[es] note: if you use www.Youtube.com to make" in text
