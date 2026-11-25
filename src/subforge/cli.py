"""subforge command line."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional

from . import REPO_URL, __version__, config  # config first: forces caches to D:
from . import ffmpeg, formatters, logging_setup
from .logging_setup import log
from .segments import build_cues

VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv",
             ".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac"}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="subforge",
        description="Generate and translate subtitles locally. No audio is ever uploaded.",
    )
    p.add_argument("--version", action="version",
                   version=f"subforge {__version__} ({REPO_URL})")
    sub = p.add_subparsers(dest="command", required=True)
    m = sub.add_parser("make", help="create subtitles for a file or a folder",
                       formatter_class=argparse.RawDescriptionHelpFormatter,
                       epilog="Examples:\n  subforge make video.mp4 --format srt --out out\n"
                              "  subforge make --batch clips --translate es --model base")
    m.add_argument("input", nargs="?", type=Path, help="video/audio file")
    m.add_argument("--batch", type=Path, metavar="DIR", help="process every media file in DIR")
    m.add_argument("--lang", default="auto", help="spoken language code or 'auto' (default)")
    m.add_argument("--format", choices=["srt", "vtt"], default="srt")
    m.add_argument("--out", type=Path, default=config.DEFAULT_OUT, help="output directory")
    m.add_argument("--translate", metavar="LANG", help="also write a translated file (needs [translate] extra)")
    m.add_argument("--burn", action="store_true",
                   help="hard-burn the subtitles (translated if --translate) into <name>.burned.mp4")
    m.add_argument("--model", choices=["base", "small", "medium"], default="small")
    m.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    m.add_argument("-v", "--verbose", action="store_true")
    d = sub.add_parser("doc", help="translate a PDF (bilingual/clean PDF, EPUB or Markdown)")
    d.add_argument("input", type=Path, help="PDF file")
    d.add_argument("--translate", metavar="LANG", help="target language (needs [translate] extra)")
    d.add_argument("--format", choices=["pdf-bilingual", "pdf-clean", "epub", "md"],
                   help="default: pdf-bilingual with --translate, md without")
    d.add_argument("--lang", default="auto", help="source language code or 'auto' (default)")
    d.add_argument("--mixed", action="store_true",
                   help="mixed-language document: detect the language per paragraph and translate "
                        "only the blocks NOT already in the target language")
    d.add_argument("--pages", metavar="RANGE", help="e.g. 1-3,5 (default: all)")
    d.add_argument("--ocr", action="store_true",
                   help="run OCR (tesseract) on scanned pages without a text layer")
    d.add_argument("--ocr-lang", default="eng", metavar="LANG",
                   help="tesseract language(s), e.g. eng, spa, eng+spa (default: eng)")
    d.add_argument("--out", type=Path, default=config.DEFAULT_OUT)
    d.add_argument("-v", "--verbose", action="store_true")

    g = sub.add_parser("manga", help="translate manga pages via the OPTIONAL external backend")
    g.add_argument("input", type=Path, help="image, folder of images or .cbz")
    g.add_argument("--translate", metavar="LANG", default="es")
    g.add_argument("--timeout", type=int, metavar="SECONDS",
                   help="kill the backend after this long (default 3600; 0 = no limit)")
    g.add_argument("--out", type=Path, default=config.DEFAULT_OUT)
    g.add_argument("-v", "--verbose", action="store_true")

    u = sub.add_parser("ui", help="start the web UI (127.0.0.1 by default)")
    u.add_argument("--port", type=int, default=8765)
    u.add_argument("--lan", action="store_true",
                   help="listen on the local-network IP (for your phone); requires a token")
    u.add_argument("--token", default="auto", metavar="auto|VALUE",
                   help="access token used with --lan (default: auto = random)")
    u.add_argument("--ip", metavar="ADDR", help="with --lan: force this IPv4 address instead of auto-detecting")
    u.add_argument("-v", "--verbose", action="store_true")
    return p


def unique_path(path: Path) -> Path:
    """Never overwrite: name.srt -> name (1).srt if it exists or is locked."""
    cand, i = path, 1
    while cand.exists():
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        i += 1
    return cand


def write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    target = unique_path(path)
    for _ in range(3):
        try:
            with open(target, "x", encoding="utf-8", newline="\n") as f:
                f.write(text)
            return target
        except FileExistsError:
            target = unique_path(path)
        except PermissionError:  # file in use / locked
            target = unique_path(target)
    raise PermissionError(f"cannot write {path} (in use or read-only)")


def collect_inputs(args) -> List[Path]:
    if args.batch:
        if not args.batch.is_dir():
            raise SystemExit(f"error: --batch folder not found: {args.batch}")
        files = sorted(f for f in args.batch.iterdir() if f.suffix.lower() in VIDEO_EXT)
        if not files:
            raise SystemExit(f"error: no media files in {args.batch}")
        return files
    if not args.input:
        raise SystemExit("error: give a file or --batch DIR (see subforge make --help)")
    if not args.input.is_file():
        raise SystemExit(f"error: file not found: {args.input}")
    return [args.input]


def burn(args, src: Path, subtitle_text: str) -> None:
    if not ffmpeg.has_video(src):
        raise RuntimeError("--burn needs a video file (no video stream found)")
    dst = unique_path(args.out / f"{src.stem}.burned.mp4")
    ffmpeg.burn_subtitles(src, subtitle_text, args.format, dst)
    log.info("wrote %s", dst)


def make(args) -> int:
    files = collect_inputs(args)
    ffmpeg.find_tool("ffmpeg"); ffmpeg.find_tool("ffprobe")  # fail early, clear message
    from .transcribe import Transcriber

    tr = Transcriber(args.model, args.device)
    lang = None if args.lang == "auto" else args.lang
    failures = 0
    pending = []  # (file, detected_lang, cues) awaiting translation
    for f in files:
        try:
            log.info("[%s] extracting audio", f.name)
            if not ffmpeg.has_audio(f):
                raise RuntimeError("no audio stream")
            wav = ffmpeg.extract_audio(f, config.TMP / f"{f.stem}.wav")
            try:
                segs, detected = tr.transcribe(wav, lang)
            finally:
                wav.unlink(missing_ok=True)
            log.info("[%s] language: %s, %d segments", f.name, detected, len(segs))
            cues = build_cues(segs)
            out = write_text(args.out / f"{f.stem}.{detected}.{args.format}",
                             formatters.render(cues, args.format))
            log.info("wrote %s", out)
            if args.translate and args.translate != detected:
                pending.append((f, detected, cues))
            elif args.burn:
                burn(args, f, formatters.render(cues, args.format))
        except Exception as e:
            failures += 1
            log.error("[%s] failed: %s", f.name, e)
            log.debug("traceback", exc_info=True)

    if pending:
        # Free the Whisper model first: both models together can exhaust RAM on small machines.
        import gc
        del tr
        gc.collect()
        from .translate import translate_cues
        for f, detected, cues in pending:
            try:
                tcues = translate_cues(cues, detected, args.translate)
                text = formatters.render(tcues, args.format)
                out = write_text(args.out / f"{f.stem}.{args.translate}.{args.format}", text)
                log.info("wrote %s", out)
                if args.burn:
                    burn(args, f, text)
            except Exception as e:
                failures += 1
                log.error("[%s] translation failed: %s", f.name, e)
                log.debug("traceback", exc_info=True)
    return 1 if failures else 0


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    logging_setup.setup(args.verbose)
    try:
        if args.command == "ui":
            from .server import run
            if args.ip and not args.lan:
                raise SystemExit("error: --ip only makes sense with --lan")
            run(args.port, lan=args.lan, token=args.token, ip=args.ip)
            return 0
        if args.command == "doc":
            from .document import NoText, ScannedPDF, convert
            from .ocr import TesseractMissing
            if not args.input.is_file():
                raise SystemExit(f"error: file not found: {args.input}")
            try:
                convert(args.input, args.out, args.translate, args.format, args.lang, args.pages,
                        args.ocr, args.ocr_lang, args.mixed)
            except (ScannedPDF, NoText, TesseractMissing) as e:
                log.error("%s", e)
                return 2
            return 0
        if args.command == "manga":
            from . import manga
            if not args.input.exists():
                raise SystemExit(f"error: not found: {args.input}")
            if not manga.available():
                log.error("%s", manga.INSTALL_HELP)
                return 2
            if args.timeout is not None:
                os.environ["SUBFORGE_MANGA_TIMEOUT"] = str(max(0, args.timeout))
            manga.translate_path(args.input, args.out, args.translate)
            return 0
        return make(args)
    except ffmpeg.FFmpegMissing as e:
        log.error("%s", e)
    except Exception as e:
        log.error("error: %s", e)
        log.debug("traceback", exc_info=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
