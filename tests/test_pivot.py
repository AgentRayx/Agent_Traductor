"""Pivot translation via English when the direct Argos package does not exist."""
import pymupdf
import pytest

from subforge import translate
from subforge.document import convert
from subforge.segments import Cue

ES = ("El libro es una obra que se publicó en la ciudad y que los lectores de todo el mundo "
      "han leído con mucho interés porque trata de la historia de las personas y de su tierra.")
ES2 = ("Este es el segundo párrafo del documento, que también está escrito en español y que no "
       "debe ser traducido por el programa porque ya está en el idioma de destino.")
EN = ("The history of the printing press is a story of how knowledge was shared with the world. "
      "It was invented in the fifteenth century and it changed the way that people read.")
FR = ("Le livre est une oeuvre que les lecteurs de la ville ont lue avec beaucoup d'intérêt, "
      "et il est dans la bibliothèque pour les enfants qui sont dans la classe.")
FR_DOUBT = "Le marché ouvre dans Lyon demain"  # only 2 French stop-words: weak evidence


class FakeTr:
    def __init__(self):
        self.calls = []

    def translate(self, text, src, dst):
        self.calls.append((src, dst))
        return f"<{src}>{dst}:{text}"


@pytest.fixture
def argos(monkeypatch):
    real = translate.translate_texts
    fake = FakeTr()
    translate._ROUTES.clear()
    monkeypatch.setattr(translate, "_argos", lambda: (None, fake))
    monkeypatch.setattr(translate, "_installed_pairs",
                        lambda: {("en", "es"), ("es", "en"), ("fr", "en"), ("en", "fr")})
    monkeypatch.setattr(translate, "_remote_pairs", lambda: set())
    installed = []
    monkeypatch.setattr(translate, "ensure_pair", lambda a, b: installed.append((a, b)))
    monkeypatch.setattr("subforge.translate.translate_texts", real)  # undo the autouse-style fakes
    yield fake, installed
    translate._ROUTES.clear()


def _pdf(tmp_path, texts):
    doc = pymupdf.open()
    p = doc.new_page()
    y = 40
    for t in texts:
        p.insert_textbox(pymupdf.Rect(50, y, 500, y + 60), t, fontsize=10)
        y += 80
    path = tmp_path / "m.pdf"
    doc.save(path)
    return path


def test_plan_prefers_direct_then_pivot(argos):
    assert translate.plan_route("en", "es") == [("en", "es")]
    assert translate.plan_route("fr", "es") == [("fr", "en"), ("en", "es")]


def test_no_pivot_possible_lists_available_pairs(argos, monkeypatch):
    monkeypatch.setattr(translate, "_remote_pairs", lambda: {("de", "en"), ("en", "de")})
    with pytest.raises(translate.TranslationUnavailable) as e:
        translate.plan_route("ja", "es")
    msg = str(e.value)
    assert "ja->en->es" in msg and "en->es" in msg and "es->en" in msg and "de->en" not in msg


def test_offline_and_not_installed_says_so(argos, monkeypatch):
    monkeypatch.setattr(translate, "_installed_pairs", lambda: set())
    with pytest.raises(translate.TranslationUnavailable) as e:
        translate.plan_route("fr", "es")
    assert "unreachable" in str(e.value)


def test_translate_texts_pivots_and_installs_both_hops(argos, caplog):
    fake, installed = argos
    caplog.set_level("INFO", logger="subforge")
    out = translate.translate_texts(["bonjour tout le monde"], "fr", "es")
    assert out == ["<en>es:<fr>en:bonjour tout le monde"]
    assert fake.calls == [("fr", "en"), ("en", "es")]
    assert installed == [("fr", "en"), ("en", "es")]
    assert "pivote fr->en->es" in caplog.text


def test_translate_cues_pivots_too(argos):
    fake, _ = argos
    out = translate.translate_cues([Cue(0, 1, "salut")], "fr", "es")
    assert "<en>es:<fr>en:salut" in out[0].text and fake.calls == [("fr", "en"), ("en", "es")]


def test_mixed_es_en_fr_doc_uses_pivot_only_for_french(argos, tmp_path):
    fake, _ = argos
    path = _pdf(tmp_path, [ES, EN, ES2, FR])
    out = convert(path, tmp_path / "o", translate="es", fmt="md", mixed=True)
    text = out.read_text(encoding="utf-8")
    assert f"<en>es:{EN}" in text                      # en -> es, direct
    assert "<en>es:<fr>en:Le livre est une" in text     # fr -> en -> es
    assert "El libro es una obra" in text and ">es:El libro" not in text and ">es:Este es" not in text
    assert fake.calls == [("en", "es"), ("fr", "en"), ("en", "es")]


def test_doubtful_minority_block_is_translated_and_reported(argos, tmp_path):
    path = _pdf(tmp_path, [ES, ES2, ES, FR_DOUBT])
    notes = []
    out = convert(path, tmp_path / "o", translate="es", fmt="md", mixed=True, notes=notes)
    assert "<en>es:<fr>en:Le marché ouvre" in out.read_text(encoding="utf-8")  # translated anyway
    assert any("dudosa" in n and "'fr'" in n for n in notes)


def test_confident_minority_block_is_not_flagged(argos, tmp_path):
    notes = []
    convert(_pdf(tmp_path, [ES, ES2, ES, FR]), tmp_path / "o", translate="es", fmt="md",
            mixed=True, notes=notes)
    assert not any("dudosa" in n for n in notes)
