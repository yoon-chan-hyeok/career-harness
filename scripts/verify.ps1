param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location $taskRoot
if (-not $PythonPath) { $PythonPath = @('.venv\Scripts\python.exe','..\..\.venv\Scripts\python.exe') | Where-Object { Test-Path $_ } | Select-Object -First 1 }
if (-not $PythonPath) { throw '먼저 개발 환경을 설치해 주세요.' }
$PythonPath = (Resolve-Path $PythonPath).Path
$env:PYTHONPATH = Join-Path $taskRoot 'backend'
$env:TMP = Join-Path $taskRoot 'work\tmp'
$env:TEMP = $env:TMP
New-Item -ItemType Directory -Force $env:TMP | Out-Null
& $PythonPath scripts/check_privacy.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonPath -m ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $PythonPath -m pyright --pythonpath $PythonPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$taskTestPath = Join-Path $env:TEMP ('v-' + [guid]::NewGuid().ToString('N').Substring(0,12))
if (Test-Path -LiteralPath $taskTestPath) { throw '검사 임시 경로가 이미 있습니다. 다시 실행해 주세요.' }
& $PythonPath -m pytest -q -p no:cacheprovider --basetemp $taskTestPath
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Push-Location frontend
$env:NEXT_TELEMETRY_DISABLED = '1'
npm run lint
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run typecheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run test:auth
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run test:deploy
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run test:upgrades
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
npm run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Pop-Location
