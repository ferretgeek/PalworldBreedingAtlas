$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = Join-Path $projectRoot 'src'
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $sourceRoot

$python = Get-Command python -ErrorAction Stop
& $python.Source -m pal_breed_helper
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

