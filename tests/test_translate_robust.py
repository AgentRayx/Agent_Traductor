from subforge import translate


class Flaky:
    def __init__(self, fail_times):
        self.fail, self.calls = fail_times, 0

    def translate(self, text, src, dst):
        self.calls += 1
        if self.fail > 0:
            self.fail -= 1
            raise RuntimeError("mkl_malloc: failed to allocate memory")
        return text.upper()


def test_long_paragraph_is_chunked_by_sentence():
    text = " ".join(f"Sentence number {i} is here." for i in range(60))
    chunks = translate._chunks(text, 200)
    assert len(chunks) > 5 and all(len(c) <= 230 for c in chunks)
    assert " ".join(chunks) == text


def test_retries_transient_memory_errors(monkeypatch):
    monkeypatch.setattr(translate.time, "sleep", lambda s: None)
    t = Flaky(2)
    assert translate._translate_robust(t, "hello. world.", "en", "es") == "HELLO. WORLD."
    assert t.calls == 3


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(translate.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(RuntimeError):
        translate._translate_robust(Flaky(99), "hi", "en", "es")


def test_stanza_never_downloads_resources(monkeypatch):
    """Argos' stanza.Pipeline must run with DownloadMethod.NONE (no GitHub call on every run)."""
    import sys
    import types

    seen = {}

    class DM:
        NONE = "NONE"

    def pipeline(*a, **kw):
        seen.update(kw)

    fake = types.ModuleType("stanza")
    fake.Pipeline, fake.DownloadMethod = pipeline, DM
    monkeypatch.setitem(sys.modules, "stanza", fake)
    from subforge import translate

    translate._stanza_offline()
    translate._stanza_offline()  # idempotent
    fake.Pipeline(lang="en", dir="x")
    assert seen["download_method"] == "NONE"
    fake.Pipeline(lang="en", download_method="X")
    assert seen["download_method"] == "X"  # an explicit choice is respected
