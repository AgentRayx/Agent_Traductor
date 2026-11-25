# subtitle-forge

**ES** · [EN below](#english)

Subtítulos automáticos y traducción **100 % locales** para cualquier vídeo: `.srt` / `.vtt` con faster-whisper y Argos Translate.

> 🔒 **Privacy-first:** el audio nunca se sube a ningún servidor. La red solo se usa para la descarga inicial de modelos (a `.cache`/`.data` dentro del proyecto).

## Principio del proyecto: funciona en cualquier computadora
Regla permanente: debe poder usarse en **cualquier PC** — CPU modesto, **sin GPU**, y **sin dependencias de GBs en el core**.
- El core (`pip install -e .`) solo trae `faster-whisper`, `pymupdf` y `ebooklib` (decenas de MB); la GPU (CUDA) es siempre opcional y nunca necesaria.
- Todo lo pesado (torch, modelos de manga, el programa tesseract) vive **fuera del venv** como backend externo opcional.
- Pensado para poca RAM: los modelos se cargan de a uno (Whisper se libera antes de traducir) y la traducción reintenta ante fallos de memoria.
- Una función que exija GPU/GBs de dependencias no entra al core.

## Demo
```
> subforge make demo.mp4 --model base
[demo.mp4] language: en, 1 segments
wrote out\demo.en.srt

1
00:00:00,000 --> 00:00:05,000
Hello everyone. Welcome to this short
demonstration of subtitle forge,
```

## Descargas e instalación

| Canal | Para quién | Cómo |
|---|---|---|
| **Portable (.zip)** | Windows, sin instalar nada | Descomprime y ejecuta `subforge.exe` desde una terminal (ver abajo) |
| **Instalador (.exe)** | Windows, instalación normal | Instala en Program Files, accesos directos, desinstalador, opción de añadir al PATH |
| **PyPI / código fuente** | Linux, macOS, desarrollo | `pip install subtitle-forge` o `git clone` + `pip install -e .` |

### Variantes `full` y `lite` (Windows)
Medimos qué carga una traducción Argos real: arrastra **PyTorch (CPU) + Stanza + spaCy** (~0,5 GB más), por eso hay dos paquetes:

| | `full` | `lite` |
|---|---|---|
| Subtítulos (Whisper), quemar, lotes | ✅ | ✅ |
| Documentos PDF/EPUB/MD + **OCR** | ✅ | ✅ |
| Interfaz web / QR para el celular | ✅ | ✅ |
| **Traducción offline** (Argos) | ✅ | ❌ |
| Incluye ffmpeg + Tesseract (eng, spa) | ✅ | ✅ |

La **lite** no puede traducir: el programa lo dice claramente. Para subir de nivel descarga la **full**, o usa la instalación por pip (`pip install "subtitle-forge[translate]"`), que no tiene esa limitación. (Un `.exe` empaquetado no puede ampliarse con `pip`.)
Los modelos (Whisper ~150 MB, paquetes de traducción) **no vienen incluidos**: se descargan una sola vez en el primer uso.

### Dónde guarda sus datos
- **Portable:** todo junto al `.exe` (`.cache`, `.data`, `out`, `.logs`), gracias al archivo `portable.flag` del zip. Borrar la carpeta lo elimina todo.
- **Instalado en Program Files:** esa carpeta es de solo lectura para un usuario normal, así que modelos, salida y logs van a `%LOCALAPPDATA%\subforge` (en C:, el estándar de Windows). Desinstalar **no** borra esa carpeta (conserva tus modelos descargados); bórrala a mano si quieres liberar espacio.
- **Desde el código fuente:** dentro de la carpeta del proyecto, como siempre.
- `SUBFORGE_ROOT` fuerza otra carpeta de datos.

### Linux y macOS (modo dev)
```bash
git clone https://github.com/AgentRayx/Agent_Traductor.git
cd subforge
python3 -m venv .venv && source .venv/bin/activate
pip install -e .                    # núcleo; extras: .[translate] .[ui] .[ocr] .[dev]
pip install -e ".[translate,ui,ocr]"
sudo apt install ffmpeg tesseract-ocr tesseract-ocr-spa      # macOS: brew install ffmpeg tesseract
subforge --version
```

### Licencias de lo que se distribuye (importante)
El código de subtitle-forge es MIT, pero los **binarios** incluyen componentes con otras licencias: **ffmpeg (GPL-3.0)** como programa aparte, y **PyMuPDF y EbookLib (AGPL-3.0)** enlazados dentro del `.exe`. Quien redistribuya los paquetes debe cumplir esas licencias (incluida la oferta del código fuente). Detalle en `THIRD_PARTY_NOTICES.txt` dentro de cada paquete.

## Instalación para desarrollo (Windows)
```powershell
cd D:\dev\subtitle-forge
py -3.10 -m venv .venv
. .\scripts\env.ps1            # fuerza caches/temporales a D:
pip install -e .               # núcleo (faster-whisper)
pip install -e .[translate]    # opcional: traducción offline (Argos)
pip install -e .[dev]          # tests
```
**ffmpeg:** copia `ffmpeg.exe` y `ffprobe.exe` (build *essentials* de gyan.dev) a `bin\` — no toca C:.
Alternativa: `winget install Gyan.FFmpeg` (instala en C:).

## Uso
```
subforge make video.mp4 --format srt --out out
subforge make --batch carpeta --translate es --model base
```
Opciones: `--lang auto|xx`, `--format srt|vtt`, `--out DIR`, `--translate LANG`, `--model base|small|medium`, `--device cpu|cuda`, `-v`. Si el archivo de salida existe o está en uso, se crea `nombre (1).srt`.

## UI local
`pip install -e .[ui]` y luego `subforge ui` → http://127.0.0.1:8765 (arrastrar vídeo, elegir idioma destino, descargar .srt/.vtt). Escucha **solo** en 127.0.0.1 y rechaza cabeceras `Host` ajenas.

## Quemar subtítulos y lote
`subforge make video.mp4 --burn` genera `video.burned.mp4` con los subtítulos incrustados (traducidos si usas `--translate`). Con `--batch carpeta --translate es` se traduce cada archivo; Whisper se libera de memoria antes de cargar Argos.

## Modo documentos (Hito 5)
```
subforge doc libro.pdf --translate es                      # PDF bilingüe (por defecto)
subforge doc libro.pdf --translate es --format epub        # pdf-bilingual | pdf-clean | epub | md
subforge doc libro.pdf --translate es --pages 1-3,7 --out out
```
- `pdf-bilingual`: páginas e imágenes intactas; el texto se regenera con el **original en gris y la traducción debajo**. `pdf-clean`: solo la traducción.
- `epub` / `md`: todo el texto por página (original citado + traducción), sin re-composición tipográfica.
- Idioma de origen autodetectado (`--lang xx` para forzarlo). Correos/URLs se dejan intactos.
- **PDFs escaneados** (sin capa de texto): se detectan y el comando termina con un error que sugiere `--ocr`.
- Limitaciones conocidas: la fuente integrada solo cubre alfabetos latinos en el PDF regenerado (CJK saldría vacío; usa `epub`/`md`); **en maquetaciones de varias columnas, bloques densos o de autores, el texto traducido puede solaparse con el siguiente bloque** (limitación documentada; no resuelta todavía).

### OCR para PDFs escaneados
```
subforge doc escaneado.pdf --ocr --translate es --format md
subforge doc escaneado.pdf --ocr --ocr-lang spa --translate en --format epub
```
Solo CPU: cada página se convierte a imagen a 150 dpi (de a una, para cuidar la RAM) y se reconoce con **Tesseract**. Solo se aplica OCR a las páginas sin texto; las que ya tienen capa de texto se leen normal. `--ocr-lang` acepta códigos de tesseract (`eng` por defecto, `spa`, `eng+spa`...).

Tesseract es un **programa aparte** (no se instala con pip). Instala los envoltorios Python con `pip install -e .[ocr]` y luego el programa:
- **Windows:** `winget install UB-Mannheim.TesseractOCR` (instala en C:). Para dejarlo todo en un solo disco, extrae el instalador de [UB-Mannheim](https://github.com/UB-Mannheim/tesseract/releases) con 7-Zip en `bin\tesseract\` y copia los idiomas `*.traineddata` (de [tessdata_fast](https://github.com/tesseract-ocr/tessdata_fast)) a `bin\tesseract\tessdata\`.
- **Linux:** `sudo apt install tesseract-ocr` (idiomas extra: `tesseract-ocr-spa`, etc.).
- Se busca, en orden: variable `SUBFORGE_TESSERACT` (ruta al ejecutable), `bin\tesseract\`, el PATH y `Program Files\Tesseract-OCR`. Si falta, el comando explica cómo instalarlo.
- La calidad depende del escaneo; el OCR puede equivocar letras en imágenes borrosas.

## Manga (backend externo opcional)
`subforge manga pagina.png|carpeta|tomo.cbz --translate es` usa [manga-image-translator](https://github.com/zyddnys/manga-image-translator) (detección de burbujas + OCR + inpaint + re-lettering) **solo si ya está instalado aparte**. Torch y sus modelos **nunca** van en este venv. Si no se detecta, el comando y la pestaña "Manga" de la UI quedan deshabilitados con instrucciones.
```powershell
# 1) instálalo en SU PROPIO venv (ver su README), p. ej. D:\dev\manga-mt\.venv
# 2) dile a subforge dónde está:
$env:SUBFORGE_MANGA_PYTHON = "D:\dev\manga-mt\.venv\Scripts\python.exe"
#    (o SUBFORGE_MANGA_CMD con el prefijo completo del comando, o un ejecutable en bin\)
```
**Línea de comandos del backend.** Como el CLI de manga-image-translator cambia entre versiones, subforge prueba en orden:
1. `local -i {IN} -o {OUT} --config-file {CFG}`
2. `--mode batch -i {IN} -o {OUT} --config-file {CFG}`

Un intento cuenta como fallido si sale con error **o** sale con 0 sin generar imágenes. Si fallan todos, el error muestra el stderr de cada intento. Salida de emergencia: `SUBFORGE_MANGA_ARGS` define la plantilla exacta (argumentos *después* del prefijo del comando; `{IN}`, `{OUT}` y `{CFG}` se sustituyen y las rutas con espacios son seguras). Si está definida se usa **tal cual y es la única** plantilla:
```powershell
$env:SUBFORGE_MANGA_ARGS = "translate --input {IN} --output {OUT} --config-file {CFG}"
```

**Timeout.** El backend se mata (con sus procesos hijos) tras 3600 s por defecto y se informa `manga backend timeout`. Cámbialo con `SUBFORGE_MANGA_TIMEOUT=<segundos>` o `subforge manga ... --timeout <segundos>`; `0` = sin límite.

**Carpetas.** Se recorren de forma recursiva (`rglob`) y las imágenes se aplanan en una sola carpeta de trabajo; si dos archivos tienen el mismo nombre (`cap1/001.png`, `cap2/001.png`) los siguientes reciben sufijo `_1`, `_2`… (`001.png`, `001_1.png`, `001_2.png`; sin distinguir mayúsculas). La salida también es plana, en orden alfabético de ruta.

> ⚠️ La integración está probada contra un backend *de prueba* (orquestación, plantillas, timeout, cbz, carpetas), **no** contra manga-image-translator real. Si tu versión usa otra sintaxis, usa `SUBFORGE_MANGA_ARGS`.

## UI desde el celular (`--lan`)
```
subforge ui --lan [--token auto|VALOR] [--port 8765] [--ip 192.168.1.50]
```
Escucha en la IP de tu **Wi-Fi real** (no en 127.0.0.1): se prefiere el adaptador Wi-Fi/WLAN y se descartan las IPs falsas (`169.254.*` y adaptadores VMware, VirtualBox, TAP, OpenVPN, Kaspersky, WSL/Hyper-V). Con `--ip` puedes forzar otra, imprime la URL y un **QR** (extra `[ui]`), y exige un **token aleatorio** en la URL (después queda en una cookie). Servicio HTTP sin cifrar: úsalo solo en redes de confianza y detenlo con Ctrl+C al terminar.
Firewall de Windows (PowerShell **como administrador**, perfil Privado), y quítalo al terminar:
```powershell
New-NetFirewallRule -DisplayName "subforge-ui" -Direction Inbound -Protocol TCP -LocalPort 8765 -Action Allow -Profile Private
Remove-NetFirewallRule -DisplayName "subforge-ui"
```
El comando imprime qué IP eligió; si no es la correcta, usa `--ip`.

## Construir los paquetes (mantenedores)
Todo se construye en D: (caches y temporales ya forzados por `scripts\env.ps1`). Requiere `pip install -e ".[build,translate,ui,ocr]"`, `bin\ffmpeg.exe`, `bin\ffprobe.exe` y `bin\tesseract\` (con `tessdata\eng` y `spa`).
```powershell
. .\scripts\env.ps1
.\scripts\build_exe.ps1 -Variant full        # dist\subforge-portable\ + subforge-<ver>-win64-portable-full.zip
.\scripts\build_exe.ps1 -Variant lite        # dist\subforge-portable-lite\ + ...-lite.zip
.\scripts\build_installer.ps1 -Variant full  # dist\subforge-<ver>-win64-setup-full.exe (Inno Setup 6, ver. más abajo)
```
`build_exe.ps1` copia ffmpeg y tesseract dentro del paquete al construir (por eso `bin\` puede seguir en `.gitignore`). Inno Setup 6 se instala en `D:\dev\tools\InnoSetup` (o apunta `INNO_HOME`).

**Python para construir:** los paquetes publicados se construyen con **Python 3.14.6** en un venv aparte (`py -3.14 -m venv D:\dev\venv314`, luego `D:\dev\venv314\Scripts\python.exe -m pip install --only-binary=:all: -e ".[translate,ui,ocr,dev,build]"`; todas las dependencias, incluido torch CPU, tienen wheels para 3.14 y los 62 tests pasan) y se invocan con `-Python`:
```powershell
.\scripts\build_exe.ps1 -Variant full -Python D:\dev\venv314\Scripts\python.exe
```
Evita el Python **3.10.0 exacto**: PyInstaller falla por un bug de `dis` (arreglado en 3.10.1); el `.spec` lo esquiva, pero no es lo recomendable. El código sigue soportando Python >= 3.9 para quien lo instale con pip.

### Publicar (pasos manuales: nada se publica automáticamente)
1. Sube la versión en `src/subforge/__init__.py` y reconstruye los paquetes.
2. **PyPI** (nombre de distribución `subtitle-forge`; `subforge` ya está ocupado en PyPI por otro proyecto; el comando sigue siendo `subforge`):
   ```powershell
   python -m build                 # -> dist\subtitle_forge-<ver>.tar.gz y .whl
   python -m twine check dist\subtitle_forge-*
   python -m twine upload --repository testpypi dist\subtitle_forge-*   # ensayo
   python -m twine upload dist\subtitle_forge-*                         # real (token de PyPI)
   ```
3. **GitHub Releases:** crea la etiqueta `v<ver>` y adjunta los `.zip` y `setup-*.exe` de `dist\`.
4. **Landing:** `docs/landing/index.html` es estática; en GitHub Pages elige la carpeta `docs/landing`.

## Roadmap
- **Hito 4 — traducción en vivo:** *por definir*. Requeriría captura de audio del sistema (loopback) y, para ir en tiempo real, aceleración CUDA, lo que choca con el principio de portabilidad; no se implementa hasta resolverlo.
- **Hito 5 — modo documentos:** ✅ PDF/EPUB/MD, manga como backend externo, pestaña "Documento" y modo LAN.
- **Hito 6:** ✅ distribución: exe portátil (full/lite), instalador Windows, build para PyPI y landing.
- **Hito 5.1:** ✅ OCR para PDFs escaneados (`--ocr`) e IP correcta en `--lan` (+ `--ip`).
- Pendiente: mejor re-maquetado de columnas (solapado de texto en el PDF bilingüe).

## Caches en D:
`HF_HOME`, `XDG_CACHE_HOME`, `XDG_DATA_HOME`, `PIP_CACHE_DIR`, `TMP/TEMP` se fuerzan a `.cache`, `.data` y `.tmp` (ver `scripts/env.ps1` y `src/subforge/config.py`). Logs en `.logs`.

## Tests
`pytest` (los tests con modelos reales llevan `@pytest.mark.slow` y se omiten).

---
## English
Fully **local** subtitle generation and translation for any video (faster-whisper + Argos Translate). **Privacy-first:** audio never leaves your machine; the network is used only for the one-time model download.

**Install:** Windows portable `.zip` / installer from GitHub Releases (`full` = with translation, `lite` = without; ffmpeg + Tesseract bundled), or `pip install subtitle-forge` (command: `subforge`). From source: create a venv, `. .\scripts\env.ps1`, `pip install -e .` (add `[translate]`, `[dev]` as needed). Put `ffmpeg.exe`/`ffprobe.exe` in `bin\` or install with `winget install Gyan.FFmpeg`.

**Usage:** `subforge make video.mp4 --format vtt --translate es --model small`. See `subforge make --help`.

All caches/temp files are forced under the project folder (`.cache`, `.data`, `.tmp`, `.logs`). MIT licensed.
