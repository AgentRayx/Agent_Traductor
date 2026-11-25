import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from subforge import server
from subforge.server import HOST, create_app


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://127.0.0.1")


def test_host_is_loopback():
    assert HOST == "127.0.0.1"


def test_index_and_languages(client):
    assert "subtitle-forge" in client.get("/").text
    assert "es" in client.get("/api/languages").json()


def test_rejects_foreign_host():
    c = TestClient(create_app(), base_url="http://evil.example")
    assert c.get("/").status_code == 403


def test_subtitles_download(client, monkeypatch):
    monkeypatch.setattr(server.ffmpeg, "find_tool", lambda n: n)
    monkeypatch.setattr(server, "process_upload", lambda *a: ("1\n00:00:00,000 --> 00:00:01,000\nhola\n", "en", "es"))
    r = client.post("/api/subtitles", files={"file": ("mi vídeo.mp4", b"data")},
                    data={"format": "srt", "translate": "es"})
    assert r.status_code == 200
    assert "hola" in r.text
    assert 'filename="mi v_deo.es.srt"' in r.headers["content-disposition"]
    assert r.headers["x-detected-language"] == "en"


def test_ui_has_document_tab(client):
    html = client.get("/").text
    assert 'data-tab="doc"' in html and "Documento" in html and "/api/document" in html


def test_capabilities_manga_disabled(client, monkeypatch):
    from subforge import manga
    monkeypatch.setattr(manga, "find_backend", lambda: None)
    caps = client.get("/api/capabilities").json()
    assert caps["manga"] is False and "OUTSIDE this venv" in caps["manga_help"]
    r = client.post("/api/manga", files={"file": ("a.png", b"x")}, data={"translate": "es"})
    assert r.status_code == 501


def test_document_endpoint(client, tmp_path, monkeypatch):
    import pymupdf
    monkeypatch.setattr("subforge.translate.translate_texts", lambda ts, s, d: [f"[{d}] {t}" for t in ts])
    doc = pymupdf.open()
    doc.new_page().insert_textbox(
        pymupdf.Rect(50, 50, 500, 150),
        "The history of the printing press is a story of how knowledge was shared with the world. "
        "It was invented in the fifteenth century and it changed the way that people read.", fontsize=11)
    pdf = tmp_path / "x.pdf"
    doc.save(pdf)
    r = client.post("/api/document", files={"file": ("Libro.pdf", pdf.read_bytes())},
                    data={"translate": "es", "format": "md"})
    assert r.status_code == 200 and "[es] The history" in r.text
    assert 'filename="Libro.es.md"' in r.headers["content-disposition"]
    assert client.post("/api/document", files={"file": ("a.txt", b"x")},
                       data={"translate": "es"}).status_code == 400


def test_token_required_in_lan_mode():
    c = TestClient(create_app(token="t" * 20, allowed_hosts={"127.0.0.1", "192.168.1.5"}),
                   base_url="http://192.168.1.5")
    assert c.get("/").status_code == 401
    assert c.get("/?token=wrong").status_code == 401
    ok = c.get("/?token=" + "t" * 20)
    assert ok.status_code == 200 and "sf_token" in ok.headers["set-cookie"]
    assert c.get("/api/languages").status_code == 200  # cookie now authorises API calls
    other = TestClient(create_app(token="t" * 20, allowed_hosts={"192.168.1.5"}), base_url="http://evil.example")
    assert other.get("/?token=" + "t" * 20).status_code == 403


def test_bad_format_and_language(client):
    f = {"file": ("a.mp4", b"x")}
    assert client.post("/api/subtitles", files=f, data={"format": "doc"}).status_code == 400
    assert client.post("/api/subtitles", files=f, data={"translate": "xx"}).status_code == 400


def test_document_endpoint_mixed(client, tmp_path, monkeypatch):
    import pymupdf
    monkeypatch.setattr("subforge.translate.translate_texts", lambda t, s, d: [f"[{d}] {x}" for x in t])
    es = ("El libro es una obra que se publicó en la ciudad y que los lectores de todo el mundo "
          "han leído con mucho interés porque trata de la historia de las personas.")
    en = ("The history of the printing press is a story of how knowledge was shared with the world. "
          "It was invented in the fifteenth century and it changed the way that people read.")
    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_textbox(pymupdf.Rect(50, 50, 500, 130), es, fontsize=11)
    p.insert_textbox(pymupdf.Rect(50, 200, 500, 280), en, fontsize=11)
    pdf = tmp_path / "m.pdf"
    doc.save(pdf)
    f = {"file": ("m.pdf", pdf.read_bytes())}
    r = client.post("/api/document", files=f, data={"translate": "es", "format": "md"})
    assert r.status_code == 400 and "--mixed" in r.json()["detail"]  # suggested, not silently guessed
    r = client.post("/api/document", files=f, data={"translate": "es", "format": "md", "mixed": "true"})
    assert r.status_code == 200 and f"[es] {en}" in r.text and "[es] El libro" not in r.text
