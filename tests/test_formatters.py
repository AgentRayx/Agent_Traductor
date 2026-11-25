import pytest

from subforge.formatters import format_timestamp, to_srt, to_vtt
from subforge.segments import Cue


def test_timestamp():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(3661.5, ".") == "01:01:01.500"
    assert format_timestamp(59.9996) == "00:01:00,000"


def test_srt():
    out = to_srt([Cue(0, 1.5, "Hola"), Cue(2, 3, "a\nb")])
    assert out == "1\n00:00:00,000 --> 00:00:01,500\nHola\n\n2\n00:00:02,000 --> 00:00:03,000\na\nb\n"


def test_vtt():
    out = to_vtt([Cue(0, 1, "Hi")])
    assert out.startswith("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi")


def test_invalid_overlap():
    with pytest.raises(ValueError):
        to_srt([Cue(0, 2, "a"), Cue(1, 3, "b")])


def test_invalid_zero_length():
    with pytest.raises(ValueError):
        to_vtt([Cue(1, 1, "a")])
