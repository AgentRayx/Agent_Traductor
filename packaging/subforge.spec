# PyInstaller spec (onedir). Variant via env SUBFORGE_VARIANT = full | lite
#   full: includes translation (argostranslate + stanza + CPU torch, ~0.5 GB more)
#   lite: no translation engine
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

# Workaround for the CPython 3.10.0 `dis` bug (IndexError in _get_const_info, fixed in 3.10.1):
# keep scanning instead of aborting. Building with Python >= 3.10.1 makes this patch a no-op.
import dis
from PyInstaller.lib.modulegraph import util as _mgu


def _safe_iterate_instructions(code_object):
    try:
        for i in dis.get_instructions(code_object):
            if i.opname != "EXTENDED_ARG":
                yield i
    except IndexError:
        return


_mgu.iterate_instructions = _safe_iterate_instructions

ROOT = Path(SPECPATH).parent
VARIANT = os.environ.get("SUBFORGE_VARIANT", "full")
assert VARIANT in ("full", "lite"), VARIANT

datas, binaries, hiddenimports = [], [], []
for pkg in ("ctranslate2", "faster_whisper", "onnxruntime", "av", "tokenizers", "pymupdf",
            "ebooklib", "pytesseract", "segno"):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hiddenimports += h
    except Exception as e:  # optional pieces must not break the build
        print("collect_all skipped", pkg, e)
for pkg in ("uvicorn", "fastapi", "starlette", "anyio", "multipart", "python_multipart", "PIL"):
    try:
        hiddenimports += collect_submodules(pkg)
    except Exception as e:
        print("collect_submodules skipped", pkg, e)

if VARIANT == "full":
    for pkg in ("argostranslate", "stanza", "minisbd", "spacy", "sentencepiece"):
        try:
            d, b, h = collect_all(pkg)
            datas += d; binaries += b; hiddenimports += h
        except Exception as e:
            print("collect_all skipped", pkg, e)
    excludes = ["tkinter", "matplotlib", "IPython", "pytest", "torch.utils.tensorboard"]
else:
    excludes = ["tkinter", "matplotlib", "IPython", "pytest", "torch", "stanza", "argostranslate",
                "spacy", "minisbd", "torchvision", "torchaudio"]

datas += [(str(ROOT / "src" / "subforge" / "static"), "subforge/static")]

a = Analysis([str(ROOT / "packaging" / "entry.py")], pathex=[str(ROOT / "src")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports, excludes=excludes,
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="subforge", console=True,
          icon=None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="subforge")
