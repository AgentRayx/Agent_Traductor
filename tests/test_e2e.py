"""Short e2e: ffmpeg-generated tone + fake transcriber (no model download)."""
import re
import shutil
import subprocess

import pytest

from subforge import cli, config, ffmpeg
from subforge.segments import Segment

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") or (config.BIN / "ffmpeg.exe").exists()), reason="ffmpeg not available"
)


class FakeTranscriber:
    def __init__(self, *a, **k):
        pass

    def transcribe(self, audio, language=None):
        assert audio.exists()
        return [Segment(0.0, 1.0, "hola mundo"), Segment(1.0, 2.0, "segunda línea")], language or "es"


def make_tone(path):
    subprocess.run([ffmpeg.find_tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-f", "lavfi", "-i", "color=c=black:s=160x90:d=2",
                    "-shortest", str(path)], check=True)


@pytest.mark.parametrize("fmt", ["srt", "vtt"])
def test_make_e2e(tmp_path, monkeypatch, fmt):
    video = tmp_path / "clip.mp4"
    make_tone(video)
    assert 1.5 < ffmpeg.duration(video) < 3
    monkeypatch.setattr("subforge.transcribe.Transcriber", FakeTranscriber)
    out = tmp_path / "out"
    rc = cli.main(["make", str(video), "--format", fmt, "--out", str(out)])
    assert rc == 0
    f = next(out.glob(f"*.{fmt}"))
    text = f.read_text(encoding="utf-8")
    assert re.search(r"\d\d:\d\d:\d\d[,.]\d{3} --> \d\d:\d\d:\d\d[,.]\d{3}", text)
    assert "hola mundo" in text
    # second run must not overwrite
    cli.main(["make", str(video), "--format", fmt, "--out", str(out)])
    assert len(list(out.glob(f"*.{fmt}"))) == 2


def test_missing_ffmpeg_message(monkeypatch):
    monkeypatch.setattr(ffmpeg.shutil, "which", lambda n: None)
    monkeypatch.setattr(config, "BIN", config.BIN / "nope")
    monkeypatch.setattr(config, "BUNDLED_BIN", config.BIN / "nope2")
    with pytest.raises(ffmpeg.FFmpegMissing) as e:
        ffmpeg.find_tool("ffmpeg")
    assert "winget" in str(e.value)
