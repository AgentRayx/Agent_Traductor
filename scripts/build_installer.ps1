# Compile the Windows installer. Needs dist\subforge-portable[-lite] (run build_exe.ps1 first) and
# Inno Setup 6 (ISCC.exe). Set INNO_HOME or install it to D:\dev\tools\InnoSetup.
param([ValidateSet("full", "lite")][string]$Variant = "full")
$ErrorActionPreference = "Continue"
. "$PSScriptRoot\env.ps1"
$Root = Split-Path -Parent $PSScriptRoot
$ver = (python -c "import subforge;print(subforge.__version__)")
$iscc = @($env:INNO_HOME, "D:\dev\tools\InnoSetup") | Where-Object { $_ -and (Test-Path "$_\ISCC.exe") } | Select-Object -First 1
if (-not $iscc) { throw "ISCC.exe not found. Install Inno Setup 6 (to D:\dev\tools\InnoSetup) or set INNO_HOME." }
$src = if ($Variant -eq "full") { "$Root\dist\subforge-portable" } else { "$Root\dist\subforge-portable-lite" }
if (-not (Test-Path "$src\subforge.exe")) { throw "build the exe first: scripts\build_exe.ps1 -Variant $Variant" }
& "$iscc\ISCC.exe" "/DVariant=$Variant" "/DAppVersion=$ver" "$Root\installer\subforge.iss"
if ($LASTEXITCODE) { throw "ISCC failed" }
Get-Item "$Root\dist\subforge-$ver-win64-setup-$Variant.exe" | Select-Object Name, @{n = "MB"; e = { [math]::Round($_.Length / 1MB) } }
