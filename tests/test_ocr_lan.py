import zipfile

import pymupdf
import pytest

from subforge import ocr, server
from subforge.document import ScannedPDF, convert, extract_blocks

needs_tesseract = pytest.mark.skipif(
    not ocr.available(), reason="tesseract/pytesseract not installed (see README: OCR)")

TEXT = ("The history of the printing press is a story of how knowledge was shared with the world. "
        "It was invented in the fifteenth century and it changed the way that people read.")


@pytest.fixture(autouse=True)
def fake_translator(monkeypatch):
    monkeypatch.setattr("subforge.translate.translate_texts",
                        lambda texts, s, d: [f"[{d}] {t}" for t in texts])


@pytest.fixture
def scanned(tmp_path):
    """A 'scanned' PDF: text rendered to a picture, no text layer."""
    src = pymupdf.open()
    p = src.new_page()
    p.insert_textbox(pymupdf.Rect(50, 60, 540, 200), TEXT, fontsize=18)
    pix = p.get_pixmap(dpi=150)
    doc = pymupdf.open()
    doc.new_page().insert_image(pymupdf.Rect(0, 0, 595, 842), pixmap=pix)
    path = tmp_path / "scan.pdf"
    doc.save(path)
    with pymupdf.open(path) as chk:
        assert chk[0].get_text().strip() == ""
    return path


def test_scanned_without_ocr_suggests_flag(scanned):
    with pytest.raises(ScannedPDF) as e:
        extract_blocks(scanned)
    assert "--ocr" in str(e.value)


def test_ocr_reports_missing_tesseract(scanned, monkeypatch):
    monkeypatch.setattr(ocr, "find_tesseract", lambda: None)
    with pytest.raises(ocr.TesseractMissing) as e:
        extract_blocks(scanned, ocr=True)
    assert "winget" in str(e.value) and "apt install" in str(e.value)


@needs_tesseract
def test_ocr_extracts_text(scanned):
    blocks, _ = extract_blocks(scanned, ocr=True)
    joined = " ".join(b.text for b in blocks).lower()
    assert "printing press" in joined and "fifteenth century" in joined


@needs_tesseract
def test_ocr_translate_md_and_epub(scanned, tmp_path):
    md = convert(scanned, tmp_path / "o", translate="es", fmt="md", ocr=True)
    assert "[es]" in md.read_text(encoding="utf-8") and "printing press" in md.read_text(encoding="utf-8").lower()
    ep = convert(scanned, tmp_path / "o", translate="es", fmt="epub", ocr=True)
    with zipfile.ZipFile(ep) as z:
        body = z.read(next(n for n in z.namelist() if n.endswith("page_0001.xhtml"))).decode("utf-8")
    assert "[es]" in body and "printing" in body.lower()


@needs_tesseract
def test_ocr_bilingual_pdf(scanned, tmp_path):
    out = convert(scanned, tmp_path / "o", translate="es", fmt="pdf-bilingual", ocr=True)
    with pymupdf.open(out) as d:
        assert "[es]" in d[0].get_text()


# ----------------------------------------------------------------- --lan IP
IPCONFIG = """Configuración IP de Windows

Adaptador desconocido Local Area Connection:

   Sufijo DNS específico para la conexión. . :
   Dirección IPv4. . . . . . . . . . . . . . : 169.254.10.5

Adaptador de Ethernet Ethernet 2:

   Dirección IPv4. . . . . . . . . . . . . . : 192.168.56.1

Adaptador de Ethernet VMware Network Adapter VMnet1:

   Dirección IPv4. . . . . . . . . . . . . . : 192.168.247.1

Adaptador de Ethernet VirtualBox Host-Only Network:

   Dirección IPv4. . . . . . . . . . . . . . : 192.168.99.1

Adaptador de Ethernet TAP-Windows Adapter V9:

   Dirección IPv4. . . . . . . . . . . . . . : 172.21.129.136

Adaptador de Ethernet Kaspersky Security Data Escort Adapter:

   Dirección IPv4. . . . . . . . . . . . . . : 10.99.0.2

Adaptador de LAN inalámbrica Wi-Fi:

   Dirección IPv4. . . . . . . . . . . . . . : 10.11.133.16
   Máscara de subred . . . . . . . . . . . . : 255.255.255.0
"""


def test_parse_ipconfig_any_language():
    ads = server.parse_ipconfig(IPCONFIG)
    assert ("Adaptador de LAN inalámbrica Wi-Fi", "10.11.133.16") in ads
    assert len(ads) == 7


def test_pick_prefers_wifi_and_skips_fakes():
    assert server.pick_lan_ip(server.parse_ipconfig(IPCONFIG), "169.254.10.5") == "10.11.133.16"


@pytest.mark.parametrize("bad", ["169.254.1.1", "127.0.0.1"])
def test_fake_ips_never_chosen(bad):
    assert server.pick_lan_ip([("Wi-Fi", bad)], bad) is None


def test_fallback_to_other_real_adapter_then_route():
    assert server.pick_lan_ip([("Ethernet", "192.168.1.20")]) == "192.168.1.20"
    assert server.pick_lan_ip([("VMware Network Adapter", "192.168.1.1")], "192.168.5.5") == "192.168.5.5"


def test_forced_ip():
    assert server.lan_ip("192.168.1.50") == "192.168.1.50"
    with pytest.raises(ValueError):
        server.lan_ip("not-an-ip")
