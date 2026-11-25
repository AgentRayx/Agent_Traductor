subtitle-forge (portable)  -  offline subtitles, translation, documents and OCR.
Nothing you process leaves your computer.

Open a terminal in this folder and run:
    subforge.exe make video.mp4 --format srt
    subforge.exe make video.mp4 --translate es          (FULL build only)
    subforge.exe doc scanned.pdf --ocr --translate es --format md
    subforge.exe ui                                      -> http://127.0.0.1:8765

ffmpeg and tesseract are included (bin\). Models are downloaded ONCE on first use
(Whisper base ~150 MB; translation packages) into this folder (.cache, .data).
Portable mode: everything (models, output "out\", logs) is stored next to subforge.exe.
Delete this folder to uninstall.

Licenses: see LICENSE.txt and THIRD_PARTY_NOTICES.txt.
