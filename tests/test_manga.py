"""Manga orchestration against a STAND-IN backend (the real one is never installed here)."""
import sys
import zipfile

import pytest

from subforge import cli, manga

FAKE = '''
import shutil, sys
from pathlib import Path
a = sys.argv
inp, out = Path(a[a.index("-i") + 1]), Path(a[a.index("-o") + 1])
files = [inp] if inp.is_file() else [p for p in inp.rglob("*") if p.is_file()]
for f in files:
    shutil.copy(f, out / ("tr_" + f.name))
'''


@pytest.fixture
def backend(tmp_path, monkeypatch):
    script = tmp_path / "fake_backend.py"
    script.write_text(FAKE)
    monkeypatch.setenv("SUBFORGE_MANGA_CMD", f'"{sys.executable}" "{script}"')


@pytest.fixture
def no_backend(monkeypatch, tmp_path):
    monkeypatch.delenv("SUBFORGE_MANGA_CMD", raising=False)
    monkeypatch.delenv("SUBFORGE_MANGA_PYTHON", raising=False)
    monkeypatch.setattr(manga.shutil, "which", lambda n: None)
    monkeypatch.setattr(manga.config, "BIN", tmp_path / "nobin")


def test_unavailable_gives_instructions(no_backend, tmp_path, capsys):
    img = tmp_path / "p.png"
    img.write_bytes(b"x")
    assert not manga.available()
    assert cli.main(["manga", str(img), "--out", str(tmp_path / "o")]) == 2
    with pytest.raises(RuntimeError, match="OUTSIDE this venv"):
        manga.translate_path(img, tmp_path / "o")


def test_image(backend, tmp_path):
    img = tmp_path / "page1.png"
    img.write_bytes(b"png")
    assert cli.main(["manga", str(img), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "page1.es.png").read_bytes() == b"png"


def test_folder_and_cbz(backend, tmp_path):
    d = tmp_path / "vol"
    d.mkdir()
    for n in ("1.png", "2.jpg"):
        (d / n).write_bytes(b"i")
    (d / "notes.txt").write_text("skip")
    out = manga.translate_path(d, tmp_path / "o", "es")
    assert sorted(p.name for p in out.iterdir()) == ["tr_1.png", "tr_2.jpg"]

    cbz = tmp_path / "vol.cbz"
    with zipfile.ZipFile(cbz, "w") as z:
        z.writestr("a/1.png", b"i")
        z.writestr("../evil.png", b"x")  # traversal entry must be ignored
    out = manga.translate_path(cbz, tmp_path / "o", "en")
    with zipfile.ZipFile(out) as z:
        assert z.namelist() == ["tr_1.png"]  # stand-in backend flattens; evil.png was skipped
    assert not (tmp_path / "evil.png").exists()


def test_bad_language(backend, tmp_path):
    img = tmp_path / "p.png"
    img.write_bytes(b"x")
    with pytest.raises(ValueError):
        manga.translate_path(img, tmp_path / "o", "xx")


# ------------------------------------------------------------------ CLI templates / timeout / recursion
def _strict_backend(tmp_path, monkeypatch, accept, name="strict.py"):
    """Stand-in that only understands ONE command line and rejects everything else (exit 2)."""
    script = tmp_path / name
    script.write_text(f'''
import shutil, sys
from pathlib import Path
a = sys.argv[1:]
if a[:{len(accept)}] != {accept!r}:
    sys.stderr.write("usage error: unknown arguments " + " ".join(a[:3]))
    sys.exit(2)
inp, out = Path(a[a.index("-i") + 1]), Path(a[a.index("-o") + 1])
for f in ([inp] if inp.is_file() else [p for p in inp.rglob("*") if p.is_file()]):
    shutil.copy(f, out / ("tr_" + f.name))
''')
    monkeypatch.setenv("SUBFORGE_MANGA_CMD", f'"{sys.executable}" "{script}"')
    monkeypatch.delenv("SUBFORGE_MANGA_ARGS", raising=False)


def _img(tmp_path):
    img = tmp_path / "p.png"
    img.write_bytes(b"png")
    return img


def test_first_template_local(tmp_path, monkeypatch):
    _strict_backend(tmp_path, monkeypatch, ["local"])
    assert manga.translate_path(_img(tmp_path), tmp_path / "o").exists()


def test_falls_back_to_batch_template(tmp_path, monkeypatch):
    _strict_backend(tmp_path, monkeypatch, ["--mode", "batch"])
    out = manga.translate_path(_img(tmp_path), tmp_path / "o")
    assert out.read_bytes() == b"png"


def test_all_templates_fail_reports_every_stderr_and_escape_hatch(tmp_path, monkeypatch):
    _strict_backend(tmp_path, monkeypatch, ["something", "else"])
    with pytest.raises(RuntimeError) as e:
        manga.translate_path(_img(tmp_path), tmp_path / "o")
    msg = str(e.value)
    assert msg.count("usage error") == 2                       # one stderr per attempt
    assert "[local -i" in msg and "[--mode batch" in msg       # which template said what
    assert "SUBFORGE_MANGA_ARGS" in msg


def test_manga_args_env_overrides_templates(tmp_path, monkeypatch):
    _strict_backend(tmp_path, monkeypatch, ["translate", "--x"])
    monkeypatch.setenv("SUBFORGE_MANGA_ARGS", "translate --x -i {IN} -o {OUT} --cfg {CFG}")
    out = manga.translate_path(_img(tmp_path), tmp_path / "o")
    assert out.read_bytes() == b"png"
    # when the custom template is wrong, the built-in ones are NOT silently tried instead
    monkeypatch.setenv("SUBFORGE_MANGA_ARGS", "nope -i {IN} -o {OUT}")
    with pytest.raises(RuntimeError) as e:
        manga.translate_path(_img(tmp_path), tmp_path / "o2")
    assert str(e.value).count("usage error") == 1


def test_exit_zero_without_output_counts_as_failure(tmp_path, monkeypatch):
    script = tmp_path / "noop.py"
    script.write_text("import sys\nsys.stderr.write('did nothing')\n")
    monkeypatch.setenv("SUBFORGE_MANGA_CMD", f'"{sys.executable}" "{script}"')
    monkeypatch.delenv("SUBFORGE_MANGA_ARGS", raising=False)
    with pytest.raises(RuntimeError, match="no images"):
        manga.translate_path(_img(tmp_path), tmp_path / "o")


def test_timeout_kills_backend(tmp_path, monkeypatch):
    import time
    script = tmp_path / "slow.py"
    script.write_text("import time\ntime.sleep(60)\n")
    monkeypatch.setenv("SUBFORGE_MANGA_CMD", f'"{sys.executable}" "{script}"')
    monkeypatch.delenv("SUBFORGE_MANGA_ARGS", raising=False)
    monkeypatch.setenv("SUBFORGE_MANGA_TIMEOUT", "1")
    t0 = time.time()
    with pytest.raises(RuntimeError, match="backend timeout"):
        manga.translate_path(_img(tmp_path), tmp_path / "o")
    assert time.time() - t0 < 20  # did not wait for the 60 s sleep nor retry the second template


def test_timeout_setting(monkeypatch):
    from subforge import config
    monkeypatch.delenv("SUBFORGE_MANGA_TIMEOUT", raising=False)
    assert config.manga_timeout() == 3600
    monkeypatch.setenv("SUBFORGE_MANGA_TIMEOUT", "0")
    assert config.manga_timeout() == 0          # 0 = unlimited
    monkeypatch.setenv("SUBFORGE_MANGA_TIMEOUT", "junk")
    assert config.manga_timeout() == 3600
    assert cli.build_parser().parse_args(["manga", "x.png", "--timeout", "5"]).timeout == 5


def test_zero_timeout_means_no_limit(backend, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBFORGE_MANGA_TIMEOUT", "0")
    assert manga.translate_path(_img(tmp_path), tmp_path / "o").exists()


def test_folder_is_recursive_with_collision_safe_names(backend, tmp_path):
    d = tmp_path / "series"
    for sub in ("ch1", "ch2/extra"):
        (d / sub).mkdir(parents=True)
    (d / "ch1" / "001.png").write_bytes(b"a")
    (d / "ch2" / "001.png").write_bytes(b"b")
    (d / "ch2" / "extra" / "001.PNG").write_bytes(b"c")
    (d / "cover.jpg").write_bytes(b"d")
    (d / "ch1" / "readme.txt").write_text("skip")
    out = manga.translate_path(d, tmp_path / "o", "es")
    names = sorted(p.name for p in out.iterdir())
    assert names == sorted(["tr_001.png", "tr_001_1.png", "tr_001_2.PNG", "tr_cover.jpg"])
    assert sorted(p.read_bytes() for p in out.iterdir()) == [b"a", b"b", b"c", b"d"]  # nothing overwritten


def test_flatten_images_unit(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.png").write_bytes(b"1")
    (tmp_path / "b" / "x.png").write_bytes(b"2")
    flat = tmp_path / "flat"
    flat.mkdir()
    assert manga.flatten_images(tmp_path, flat) == 2
    assert sorted(p.name for p in flat.iterdir()) == ["x.png", "x_1.png"]
