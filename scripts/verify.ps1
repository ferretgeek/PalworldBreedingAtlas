$ErrorActionPreference = 'Stop'

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$sourceRoot = Join-Path $projectRoot 'src'
$validator = Join-Path $projectRoot 'tools\validate_data.py'
$solverTest = Join-Path $projectRoot 'tests\test_solver.js'
$solverTestModule = Join-Path $projectRoot 'tests\test_solver.mjs'

$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = $sourceRoot
$python = Get-Command python -ErrorAction Stop

Push-Location -LiteralPath $projectRoot
try {
    Write-Output '1/4 编译检查'
    & $python.Source -m compileall -q src tests tools
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Output '2/4 Python 自动化测试'
    & $python.Source -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Output '3/4 游戏数据契约校验'
    if (-not (Test-Path -LiteralPath $validator -PathType Leaf)) {
        throw "缺少数据校验器：$validator"
    }
    & $python.Source $validator
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    Write-Output '4/4 浏览器求解器测试'
    if (-not (Test-Path -LiteralPath $solverTest -PathType Leaf) -and (Test-Path -LiteralPath $solverTestModule -PathType Leaf)) {
        $solverTest = $solverTestModule
    }
    if (Test-Path -LiteralPath $solverTest -PathType Leaf) {
        $node = Get-Command node -ErrorAction Stop
        & $node.Source $solverTest
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    else {
        Write-Output '未发现 tests\test_solver.js 或 tests\test_solver.mjs，跳过独立 JavaScript 测试。'
    }
}
finally {
    Pop-Location
}

Write-Output '验证完成：所有门禁均已通过。'
