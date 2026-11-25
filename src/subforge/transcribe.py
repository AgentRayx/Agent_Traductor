"""Local transcription with faster-whisper (CTranslate2). Audio never leaves the machine."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from . import config  # noqa: F401  (must come first: sets cache env vars)
from .segments import Segment, Word


class Transcriber:
    def __init__(self, model: str = "small", device: str = "cpu", compute_type: Optional[str] = None):
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "faster-whisper is not installed. Run: pip install -e .  (inside the project venv)"
            ) from e
        if compute_type is None:
            compute_type = "int8" if device == "cpu" else "float16"
        self.model_name, self.device = model, device
        self._model = WhisperModel(
            model, device=device, compute_type=compute_type,
            download_root=str(config.CACHE / "hf"),
        )

    def transcribe(self, audio: Path, language: Optional[str] = None) -> Tuple[List[Segment], str]:
        """Returns (segments, detected_or_forced_language). language=None -> auto-detect."""
        segs, info = self._model.transcribe(
            str(audio), language=language, vad_filter=True, word_timestamps=True,
        )
        out = []
        for s in segs:  # generator: transcription happens here
            words = [Word(w.start, w.end, w.word) for w in (s.words or [])]
            out.append(Segment(s.start, s.end, s.text.strip(), words or None))
        return out, info.language
