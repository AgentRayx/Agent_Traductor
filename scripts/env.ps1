# Dot-source this file:  . .\scripts\env.ps1
# Forces every cache/temp location onto D: (C: is almost full).
$Root = Split-Path -Parent $PSScriptRoot
$env:SUBFORGE_ROOT   = $Root
$env:HF_HOME         = "$Root\.cache\hf"
$env:XDG_CACHE_HOME  = "$Root\.cache"
$env:XDG_DATA_HOME   = "$Root\.data"
$env:PIP_CACHE_DIR   = "$Root\.cache\pip"
$env:TMP             = "$Root\.tmp"
$env:TEMP            = "$Root\.tmp"
foreach ($d in $env:HF_HOME, $env:PIP_CACHE_DIR, $env:XDG_DATA_HOME, $env:TMP, "$Root\.logs", "$Root\bin") {
    New-Item -ItemType Directory -Force $d | Out-Null
}
$env:PATH = "$Root\bin;$Root\.venv\Scripts;$env:PATH"
Write-Host "subforge env ready -> $Root"
