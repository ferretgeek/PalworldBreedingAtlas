$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$spec = Join-Path $projectRoot 'pal_breed_helper.spec'
$sourceRoot = Join-Path $projectRoot 'src'
$launcher = Join-Path $projectRoot 'scripts\launcher.py'
$exePath = Join-Path $projectRoot 'dist\帕鲁配种助手.exe'
$env:PYTHONUTF8 = '1'

$python = Get-Command python -ErrorAction Stop
$pythonBits = & $python.Source -c 'import struct; print(struct.calcsize("P") * 8)'
if ($LASTEXITCODE -ne 0) {
    throw '无法确认 Python 架构，请检查当前 Python 安装。'
}
if ($pythonBits.Trim() -ne '64') {
    throw "构建必须使用 64 位 Python；当前检测到 $($pythonBits.Trim()) 位。"
}

if (Test-Path -LiteralPath $exePath -PathType Leaf) {
    try {
        $stream = [System.IO.File]::Open(
            $exePath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
        $stream.Dispose()
    }
    catch [System.UnauthorizedAccessException] {
        throw "无法写入旧版 EXE：$exePath。请检查文件权限或只读属性。"
    }
    catch [System.IO.IOException] {
        throw "旧版 EXE 正在运行或被其他程序占用：$exePath。请关闭《帕鲁配种助手》后重新构建。"
    }
}

Push-Location -LiteralPath $projectRoot
try {
    $verify = Join-Path $projectRoot 'scripts\verify.ps1'
    & $verify
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    & $python.Source -c 'import PyInstaller' 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw '缺少 PyInstaller。请先执行：python -m pip install -r requirements-dev.txt'
    }

    & $python.Source -m PyInstaller --noconfirm --clean $spec
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

$exe = Resolve-Path -LiteralPath $exePath -ErrorAction Stop
$exeInfo = Get-Item -LiteralPath $exe.Path
$inputs = @(
    Get-ChildItem -LiteralPath $sourceRoot -Recurse -File |
        Where-Object {
            $_.Extension -ne '.pyc' -and
            $_.FullName -notmatch '[\\/]__pycache__[\\/]'
        }
    Get-Item -LiteralPath $spec
    Get-Item -LiteralPath $launcher
)
$latestInput = $inputs | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
if ($null -eq $latestInput) {
    throw '没有找到可用于构建时间校验的输入文件。'
}
if ($exeInfo.LastWriteTimeUtc -le $latestInput.LastWriteTimeUtc) {
    throw (
        "构建产物不是最新：EXE 时间 $($exeInfo.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss.fff'))，" +
        "最新输入 $($latestInput.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss.fff'))：$($latestInput.FullName)"
    )
}
if ($exeInfo.Length -le 0) {
    throw "构建产物大小无效：$($exeInfo.Length) 字节。"
}

$sha256 = (Get-FileHash -LiteralPath $exeInfo.FullName -Algorithm SHA256).Hash
Write-Output "构建完成：$($exeInfo.FullName)"
Write-Output "Python 架构：$($pythonBits.Trim()) 位"
Write-Output "产物大小：$($exeInfo.Length) 字节"
Write-Output "SHA-256：$sha256"
Write-Output "最新输入：$($latestInput.FullName)（$($latestInput.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss.fff'))）"
