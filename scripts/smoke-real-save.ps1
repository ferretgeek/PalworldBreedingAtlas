param(
    [Parameter(Mandatory = $true)]
    [string]$SavePath,

    [switch]$AllowUnknown
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = Join-Path $projectRoot 'src'
$smokeScript = Join-Path $projectRoot 'tools\smoke_real_save.py'
$resolvedSave = (Resolve-Path -LiteralPath $SavePath -ErrorAction Stop).Path

$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $sourceRoot
$python = Get-Command python -ErrorAction Stop
$arguments = @($smokeScript, '--save', $resolvedSave)
if ($AllowUnknown) {
    $arguments += '--allow-unknown'
}

& $python.Source @arguments
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
