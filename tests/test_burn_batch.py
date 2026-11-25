"""Hito 3: --burn and --translate in batch mode (fake transcriber/translator, real ffmpeg)."""
import json
import shutil
import subprocess

import pytest

from subforge import cli, config, ffmpeg
from subforge.segments import Cue, Segment

pytestmark = pytest.mark.skipif(
    not (shutil.which("ffmpeg") or (config.BIN / "ffmpeg.exe").exists()), reason="ffmpeg not available"
)


class FakeTranscriber:
    def __init__(self, *a, **k):
        pass

    def transcribe(self, audio, language=None):
        return [Segment(0.0, 1.0, "hello world"), Segment(1.0, 2.0, "second line")], "en"


def fake_translate(cues, src, dst):
    return [Cue(c.start, c.end, f"[{dst}] {c.text}") for c in cues]


def make_video(path):
    subprocess.run([ffmpeg.find_tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=2", "-f", "lavfi", "-i", "color=c=blue:s=320x180:d=2",
                    "-shortest", "-pix_fmt", "yuv420p", str(path)], check=True)


def probe(path):
    r = subprocess.run([ffmpeg.find_tool("ffprobe"), "-v", "error", "-show_entries",
                        "stream=codec_type,width,height:format=duration", "-of", "json", str(path)],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


@pytest.fixture
def fakes(monkeypatch):
    monkeypatch.setattr("subforge.transcribe.Transcriber", FakeTranscriber)
    monkeypatch.setattr("subforge.translate.translate_cues", fake_translate)


def test_burn_single(tmp_path, fakes):
    v = tmp_path / "clip.mp4"
    make_video(v)
    out = tmp_path / "out"
    assert cli.main(["make", str(v), "--burn", "--out", str(out)]) == 0
    burned = out / "clip.burned.mp4"
    info = probe(burned)
    assert {s["codec_type"] for s in info["streams"]} == {"video", "audio"}
    assert (info["streams"][0].get("width") or info["streams"][1].get("width")) == 320
    assert 1.5 < float(info["format"]["duration"]) < 3


def test_batch_translate_and_burn(tmp_path, fakes):
    src = tmp_path / "in"
    src.mkdir()
    for n in ("a", "b"):
        make_video(src / f"{n}.mp4")
    out = tmp_path / "out"
    assert cli.main(["make", "--batch", str(src), "--translate", "es", "--burn", "--out", str(out)]) == 0
    names = sorted(p.name for p in out.iterdir())
    assert names == ["a.burned.mp4", "a.en.srt", "a.es.srt", "b.burned.mp4", "b.en.srt", "b.es.srt"]
    assert "[es] hello world" in (out / "a.es.srt").read_text(encoding="utf-8")
    # timestamps preserved between original and translation
    stamp = lambda p: [l for l in p.read_text(encoding="utf-8").splitlines() if "-->" in l]
    assert stamp(out / "b.en.srt") == stamp(out / "b.es.srt")


def test_burn_path_with_special_chars(tmp_path, fakes):
    v = tmp_path / "mi vídeo, (1) [x].mp4"
    make_video(v)
    out = tmp_path / "salida"
    assert cli.main(["make", str(v), "--burn", "--format", "vtt", "--out", str(out)]) == 0
    assert any(p.suffix == ".mp4" for p in out.iterdir())


def test_burn_rejects_audio_only(tmp_path, fakes):
    a = tmp_path / "tone.wav"
    subprocess.run([ffmpeg.find_tool("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", str(a)], check=True)
    out = tmp_path / "out"
    assert cli.main(["make", str(a), "--burn", "--out", str(out)]) == 1
    assert not list(out.glob("*.mp4"))
