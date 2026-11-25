# Build the portable Windows package (onedir). Usage:  .\scripts\build_exe.ps1 [-Variant full|lite]
# -Python: interpreter to build with (default: python on PATH). Python >= 3.10.1 recommended, e.g. D:\dev\venv314\Scripts\python.exe
# Output: dist\subforge-portable\ (full)  |  dist\subforge-portable-lite\ (lite)  + .zip next to it.
# Everything stays on the project drive (caches/temp forced by env.ps1).
param([ValidateSet("full", "lite")][string]$Variant = "full", [string]$Python = "python")
$ErrorActionPreference = "Continue"  # native tools log to stderr; failures are checked via $LASTEXITCODE
. "$PSScriptRoot\env.ps1"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$ver = (& $Python -c "import subforge;print(subforge.__version__)")
if ($LASTEXITCODE) { throw "python failed" }
$name = if ($Variant -eq "full") { "subforge-portable" } else { "subforge-portable-lite" }
$work = "$Root\build\$Variant"; $stage = "$Root\build\dist-$Variant"; $final = "$Root\dist\$name"
foreach ($d in $work, $stage, $final) { if (Test-Path $d) { Remove-Item $d -Recurse -Force } }
New-Item -ItemType Directory -Force "$Root\dist" | Out-Null

$env:SUBFORGE_VARIANT = $Variant
& $Python -m PyInstaller "$Root\packaging\subforge.spec" --noconfirm --clean --distpath $stage --workpath $work
if ($LASTEXITCODE) { throw "PyInstaller failed" }
Move-Item "$stage\subforge" $final

# Bundled tools: copied at build time (bin\ is git-ignored on purpose).
New-Item -ItemType Directory -Force "$final\bin\tesseract" | Out-Null
foreach ($f in "ffmpeg.exe", "ffprobe.exe") {
    if (-not (Test-Path "$Root\bin\$f")) { throw "missing bin\$f (see README)" }
    Copy-Item "$Root\bin\$f" "$final\bin\"
}
$t = "$Root\bin\tesseract"
if (-not (Test-Path "$t\tesseract.exe")) { throw "missing bin\tesseract (see README)" }
Get-ChildItem $t -File | Where-Object {
    ($_.Extension -eq ".dll") -or ($_.Name -eq "tesseract.exe")
} | Copy-Item -Destination "$final\bin\tesseract\"
New-Item -ItemType Directory -Force "$final\bin\tesseract\tessdata" | Out-Null
foreach ($d in "configs", "tessconfigs") { Copy-Item "$t\tessdata\$d" "$final\bin\tesseract\tessdata\$d" -Recurse }
foreach ($l in "eng", "spa") { Copy-Item "$t\tessdata\$l.traineddata" "$final\bin\tesseract\tessdata\" }

Copy-Item "$Root\LICENSE" "$final\LICENSE.txt"
Copy-Item "$Root\packaging\THIRD_PARTY_NOTICES.txt" "$final\"
Copy-Item "$Root\packaging\README-portable.txt" "$final\README.txt"
if ($Variant -eq "lite") { Add-Content "$final\README.txt" "`r`nBUILD: LITE (no translation engine). Use the FULL build for translation." }
# marker: data (models, out, logs) live next to the exe. The installer does NOT ship it.
Set-Content "$final\portable.flag" "portable mode: data is stored next to subforge.exe"

$zip = "$Root\dist\subforge-$ver-win64-portable-$Variant.zip"
if (Test-Path $zip) { Remove-Item $zip }
# .NET streaming zip: Compress-Archive loads files into RAM and dies (OutOfMemory) on >1 GB packages.
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($final, $zip, [IO.Compression.CompressionLevel]::Optimal, $true)
"{0}: {1:N0} MB  |  zip: {2:N0} MB" -f $final, ((Get-ChildItem $final -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), ((Get-Item $zip).Length / 1MB)
