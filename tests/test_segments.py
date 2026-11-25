from subforge.segments import Segment, Word, build_cues, split_segment, wrap_lines


def test_wrap_short_unchanged():
    assert wrap_lines("short text") == "short text"


def test_wrap_two_lines_within_limit():
    t = "this is a fairly long sentence that must be wrapped into two lines"
    lines = wrap_lines(t).split("\n")
    assert len(lines) == 2 and all(len(l) <= 42 for l in lines)


def test_split_long_segment_proportional():
    text = " ".join(["palabra"] * 30)  # 239 chars
    cues = split_segment(Segment(0.0, 30.0, text))
    assert len(cues) > 1
    assert cues[0].start == 0.0 and abs(cues[-1].end - 30.0) < 1e-6
    for c in cues:
        assert len(c.text.split("\n")) <= 2
        assert all(len(l) <= 42 for l in c.text.split("\n"))
        assert c.end - c.start <= 7.0 + 1e-6


def test_split_uses_word_times():
    words = [Word(i, i + 0.9, f"w{i}") for i in range(20)]
    seg = Segment(0, 19.9, " ".join(w.text for w in words), words)
    cues = split_segment(seg, max_duration=5)
    assert all(c.end - c.start <= 5.9 for c in cues)
    assert cues[0].start == 0


def test_build_cues_monotonic():
    segs = [Segment(0, 2, "uno"), Segment(1.5, 3, "dos"), Segment(3, 3, "tres")]
    cues = build_cues(segs)
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start + 1e-9
    assert all(c.end > c.start for c in cues)
