"""Local web UI (FastAPI). Loopback by default; --lan adds a mandatory access token."""
import gc
import hmac
import re
import secrets
import shutil
import socket
import subprocess
import sys
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from . import config  # first: caches on D:
from . import ffmpeg, formatters
from .logging_setup import log
from .segments import build_cues

HOST = "127.0.0.1"  # default bind; --lan binds the local-network IP instead
LOOPBACK_HOSTS = {"127.0.0.1", "localhost"}
MAX_UPLOAD = 4 * 1024**3
STATIC = Path(__file__).parent / "static"
COOKIE = "sf_token"

LANGS = {"": "— sin traducción / none —", "es": "Español", "en": "English", "fr": "Français",
         "de": "Deutsch", "it": "Italiano", "pt": "Português", "ja": "日本語", "zh": "中文", "ru": "Русский"}
DOC_FORMATS = ("pdf-bilingual", "pdf-clean", "epub", "md")
MIME = {".pdf": "application/pdf", ".epub": "application/epub+zip", ".md": "text/markdown",
        ".cbz": "application/vnd.comicbook+zip", ".png": "image/png", ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp"}


def process_upload(src: Path, model: str, device: str, lang: str, translate: str, fmt: str):
    """Transcribe (+ translate). Returns (subtitle_text, detected_lang, target_lang)."""
    from .transcribe import Transcriber

    if not ffmpeg.has_audio(src):
        raise ValueError("el archivo no tiene pista de audio / file has no audio stream")
    wav = ffmpeg.extract_audio(src, config.TMP / f"{uuid.uuid4().hex}.wav")
    try:
        tr = Transcriber(model, device)
        segs, detected = tr.transcribe(wav, None if lang in ("", "auto") else lang)
    finally:
        wav.unlink(missing_ok=True)
    del tr
    gc.collect()  # free Whisper before loading Argos (RAM)
    cues = build_cues(segs)
    target = detected
    if translate and translate != detected:
        from .translate import translate_cues
        cues = translate_cues(cues, detected, translate)
        target = translate
    return formatters.render(cues, fmt), detected, target


_FAKE_ADAPTERS = ("vmware", "virtualbox", "vbox", "host-only", "tap", "openvpn", "kaspersky",
                  "vethernet", "wsl", "hyper-v")
_WIFI = ("wi-fi", "wifi", "wlan", "wireless", "inalámbrica", "inalambrica", "sans fil")
_IPV4 = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def _good_ip(ip: str) -> bool:
    try:
        parts = [int(x) for x in ip.split(".")]
    except ValueError:
        return False
    return (len(parts) == 4 and all(0 <= p <= 255 for p in parts)
            and not ip.startswith(("127.", "169.254.", "0.")) and parts[0] < 224)


def parse_ipconfig(text: str) -> List[Tuple[str, str]]:
    """[(adapter name, ipv4)] from `ipconfig` output (works in any Windows UI language)."""
    out, adapter = [], ""
    for line in text.splitlines():
        if line.strip() and not line[0].isspace() and line.rstrip().endswith(":"):
            adapter = line.strip().rstrip(":")
        elif "ipv4" in line.lower() and adapter:
            m = _IPV4.search(line.split(":", 1)[-1])
            if m:
                out.append((adapter, m.group(1)))
    return out


def pick_lan_ip(adapters: List[Tuple[str, str]], route_ip: Optional[str] = None) -> Optional[str]:
    """Prefer the real Wi-Fi adapter; skip link-local and virtual/VPN/antivirus adapters."""
    real = [(n, ip) for n, ip in adapters
            if _good_ip(ip) and not any(f in n.lower() for f in _FAKE_ADAPTERS)]
    for n, ip in real:
        if any(w in n.lower() for w in _WIFI):
            return ip
    if real:
        return real[0][1]
    if route_ip and _good_ip(route_ip):
        return route_ip
    return None


def _route_ip() -> Optional[str]:
    """IP of the default route. UDP connect() sends no packets."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def _adapters() -> List[Tuple[str, str]]:
    if sys.platform == "win32":
        try:
            raw = subprocess.run(["ipconfig"], capture_output=True, timeout=10).stdout
            return parse_ipconfig(raw.decode("oem", errors="replace"))
        except (OSError, subprocess.SubprocessError):
            return []
    return []


def lan_ip(forced: Optional[str] = None) -> Optional[str]:
    """Local-network IP to serve on. `forced` (--ip) wins after validation."""
    if forced:
        try:
            socket.inet_aton(forced)
        except OSError:
            raise ValueError(f"--ip {forced!r} is not a valid IPv4 address")
        return forced
    return pick_lan_ip(_adapters(), _route_ip())


def create_app(token: Optional[str] = None, allowed_hosts=None):
    from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
    from fastapi.responses import HTMLResponse, JSONResponse, Response

    hosts = set(allowed_hosts or LOOPBACK_HOSTS)
    app = FastAPI(title="subtitle-forge", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]")
        if host not in hosts:  # blocks DNS-rebinding style access
            return JSONResponse({"error": "forbidden host"}, status_code=403)
        set_cookie = False
        if token:
            supplied = request.query_params.get("token")
            ok_q = bool(supplied) and hmac.compare_digest(supplied, token)
            cookie = request.cookies.get(COOKIE, "")
            ok_c = bool(cookie) and hmac.compare_digest(cookie, token)
            if not (ok_q or ok_c):
                return JSONResponse({"error": "token required (open the URL printed by subforge ui --lan)"},
                                    status_code=401)
            set_cookie = ok_q and not ok_c
        response = await call_next(request)
        if set_cookie:
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict")
        return response

    @app.get("/", response_class=HTMLResponse)
    def index():
        return (STATIC / "index.html").read_text(encoding="utf-8")

    @app.get("/api/languages")
    def languages():
        from . import manga
        return LANGS

    @app.get("/api/capabilities")
    def capabilities():
        from . import manga
        return {"manga": manga.available(), "manga_help": manga.INSTALL_HELP,
                "doc_formats": list(DOC_FORMATS)}

    def save_upload(file: UploadFile, job: Path, allowed_ext=None) -> Path:
        suffix = Path(file.filename or "x").suffix.lower()[:10]
        if allowed_ext and suffix not in allowed_ext:
            raise HTTPException(400, f"unsupported file type {suffix or '(none)'}; expected {', '.join(sorted(allowed_ext))}")
        src = job / ("input" + suffix)
        size = 0
        with open(src, "wb") as out:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "file too large")
                out.write(chunk)
        return src

    def new_job() -> Path:
        job = config.TMP / f"upload-{uuid.uuid4().hex}"
        job.mkdir(parents=True, exist_ok=True)
        return job

    def safe_stem(file: UploadFile, default: str) -> str:
        stem = Path(file.filename or default).stem.replace('"', "")[:80] or default
        return "".join(c if c.isascii() and c not in '\\/' else "_" for c in stem)

    @app.post("/api/subtitles")
    def subtitles(
        file: UploadFile = File(...),
        format: str = Form("srt"),
        translate: str = Form(""),
        lang: str = Form("auto"),
        model: str = Form("base"),
        device: str = Form("cpu"),
    ):
        if format not in ("srt", "vtt"):
            raise HTTPException(400, "format must be srt or vtt")
        if model not in ("base", "small", "medium") or device not in ("cpu", "cuda"):
            raise HTTPException(400, "invalid model/device")
        if translate and translate not in LANGS:
            raise HTTPException(400, "unsupported target language")
        job = new_job()
        try:
            src = save_upload(file, job)
            ffmpeg.find_tool("ffmpeg")
            text, detected, target = process_upload(src, model, device, lang, translate, format)
        except HTTPException:
            raise
        except ffmpeg.FFmpegMissing as e:
            raise HTTPException(500, str(e))
        except Exception as e:
            log.exception("ui job failed")
            raise HTTPException(500, str(e))
        finally:
            shutil.rmtree(job, ignore_errors=True)
        name = safe_stem(file, "subtitles")
        return Response(
            text, media_type="text/vtt" if format == "vtt" else "application/x-subrip",
            headers={"Content-Disposition": f'attachment; filename="{name}.{target}.{format}"',
                     "X-Detected-Language": detected},
        )

    @app.post("/api/document")
    def document(
        file: UploadFile = File(...),
        format: str = Form("pdf-bilingual"),
        translate: str = Form(""),
        lang: str = Form("auto"),
        mixed: bool = Form(False),
    ):
        from .document import NoText, ScannedPDF, convert

        if format not in DOC_FORMATS:
            raise HTTPException(400, "invalid format")
        if translate and translate not in LANGS:
            raise HTTPException(400, "unsupported target language")
        job = new_job()
        try:
            src = save_upload(file, job, {".pdf"})
            notes: list = []
            out = convert(src, job / "out", translate or None, format, lang or "auto",
                          mixed=mixed, notes=notes)
            data = out.read_bytes()
            ext = out.suffix
        except HTTPException:
            raise
        except (ScannedPDF, NoText) as e:
            raise HTTPException(422, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            log.exception("ui document job failed")
            raise HTTPException(500, str(e))
        finally:
            shutil.rmtree(job, ignore_errors=True)
        tag = translate or "text"
        suffix = ".bilingual" if format == "pdf-bilingual" else ""
        headers = {"Content-Disposition":
                   f'attachment; filename="{safe_stem(file, "document")}.{tag}{suffix}{ext}"'}
        if notes:  # percent-encoded: header values must be latin-1/ASCII
            from urllib.parse import quote
            headers["X-Notes"] = quote(" | ".join(notes))
        return Response(data, media_type=MIME.get(ext, "application/octet-stream"), headers=headers)

    @app.post("/api/manga")
    def manga_endpoint(file: UploadFile = File(...), translate: str = Form("es")):
        from . import manga

        if not manga.available():
            raise HTTPException(501, manga.INSTALL_HELP)
        if translate not in manga.LANG_CODES:
            raise HTTPException(400, "unsupported target language")
        job = new_job()
        try:
            src = save_upload(file, job, manga.IMAGE_EXT | {".cbz"})
            out = manga.translate_path(src, job / "out", translate)
            data, ext = out.read_bytes(), out.suffix
        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            log.exception("ui manga job failed")
            raise HTTPException(500, str(e))
        finally:
            shutil.rmtree(job, ignore_errors=True)
        return Response(data, media_type=MIME.get(ext, "application/octet-stream"),
                        headers={"Content-Disposition":
                                 f'attachment; filename="{safe_stem(file, "manga")}.{translate}{ext}"'})

    return app


PRIVACY_NOTICE = (
    "PRIVACY: files you upload are processed on THIS computer only and deleted afterwards.\n"
    "         LAN mode serves plain HTTP: anyone on your Wi-Fi who sees the URL (it contains the token)\n"
    "         could use this tool. Use it only on networks you trust and stop it (Ctrl+C) when done."
)


def run(port: int = 8765, lan: bool = False, token: str = "auto", ip: Optional[str] = None) -> None:
    import uvicorn

    if not lan:
        log.info("subforge UI -> http://%s:%d  (loopback only; Ctrl+C to stop)", HOST, port)
        uvicorn.run(create_app(), host=HOST, port=port, log_level="warning")
        return

    ip = lan_ip(ip)
    if not ip:
        raise RuntimeError("could not determine the local-network IP (are you connected to a network?); "
                           "use --ip ADDR to set it")
    print(f"Using IP {ip} (override with --ip)", flush=True)
    if token == "auto":
        token = secrets.token_urlsafe(16)
    elif len(token) < 16:
        raise ValueError("--token must be at least 16 characters (or use 'auto')")
    url = f"http://{ip}:{port}/?token={token}"
    print(f"\nsubforge UI (LAN) -> {url}\n", flush=True)
    try:
        import segno
        segno.make(url, error="m").terminal(compact=True)
    except ImportError:
        print("(install the [ui] extra for a QR code: pip install -e .[ui])")
    except Exception:  # console encoding problems must not stop the server
        print("(QR could not be rendered in this console; use the URL above)")
    print("\n" + PRIVACY_NOTICE)
    print(f"Windows firewall: allow inbound TCP {port} (Private network), see README. Ctrl+C to stop.\n",
          flush=True)
    uvicorn.run(create_app(token, LOOPBACK_HOSTS | {ip}), host=ip, port=port, log_level="warning")
