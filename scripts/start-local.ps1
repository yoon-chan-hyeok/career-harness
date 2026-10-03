param([string]$PythonPath = '', [int]$BackendPort = 8000, [int]$FrontendPort = 3000, [switch]$Development, [string]$QaUser = '', [string]$QaToken = '')
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
Set-Location $taskRoot
$taskWork = Join-Path $taskRoot 'work'
New-Item -ItemType Directory -Force $taskWork | Out-Null
if (-not $PythonPath) {
    $taskCandidates = @((Join-Path $taskRoot '.venv\Scripts\python.exe'), (Join-Path $taskRoot '..\..\.venv\Scripts\python.exe'))
    $PythonPath = $taskCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
}
if (-not $PythonPath) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 이상이 필요합니다.' }
    $PythonPath = Join-Path $taskRoot '.venv\Scripts\python.exe'
    & $PythonPath -m pip install -e '.[dev]'
    if ($LASTEXITCODE -ne 0) { throw 'Python 패키지 설치에 실패했습니다.' }
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
if (-not (Test-Path 'frontend\node_modules')) {
    Push-Location frontend
    npm ci
    if ($LASTEXITCODE -ne 0) { throw '웹 의존성 설치에 실패했습니다.' }
    Pop-Location
}
$taskConfigPath = Join-Path $taskRoot '.local-settings.json'
if (-not (Test-Path -LiteralPath $taskConfigPath)) {
    $taskBytes = New-Object byte[] 32
    [System.Security.Cryptography.RandomNumberGenerator]::Fill($taskBytes)
    $taskToken = [Convert]::ToHexString($taskBytes).ToLowerInvariant()
    @{ token = $taskToken; user = 'local-owner' } | ConvertTo-Json | Set-Content -LiteralPath $taskConfigPath -Encoding utf8
}
$taskConfig = Get-Content -LiteralPath $taskConfigPath -Raw | ConvertFrom-Json
$taskAuth = @{ $taskConfig.token = $taskConfig.user }
if ($QaUser -or $QaToken) {
    if ($QaUser -notmatch '^qa-[a-z0-9-]{8,80}$' -or $QaToken.Length -lt 16 -or $QaUser -eq $taskConfig.user) { throw 'QA 로그인은 별도의 qa- 계정과 16자 이상 테스트 토큰이 필요합니다.' }
    $taskAuth[$QaToken] = $QaUser
}
$env:AUTH_TOKENS = $taskAuth | ConvertTo-Json -Compress
$env:PYTHONPATH = Join-Path $taskRoot 'backend'
$env:NEXT_TELEMETRY_DISABLED = '1'
$env:BACKEND_URL = "http://127.0.0.1:$BackendPort"
& $PythonPath -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { throw '데이터베이스 마이그레이션 실패' }
# These are local development servers bound only to loopback.
$taskBackend = Start-Process -FilePath $PythonPath -ArgumentList @('-m','uvicorn','career.api:app','--host','127.0.0.1','--port',"$BackendPort") -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskWork 'backend.out.log') -RedirectStandardError (Join-Path $taskWork 'backend.err.log')
$taskNode = (Get-Command node).Source
$taskFrontendMode = if ($Development -or -not (Test-Path 'frontend\.next\BUILD_ID')) { 'dev' } else { 'start' }
$taskFrontendArgs = @('node_modules/next/dist/bin/next',$taskFrontendMode,'--hostname','127.0.0.1','--port',"$FrontendPort")
if ($taskFrontendMode -eq 'start' -and (Test-Path 'frontend\.next\standalone\server.js')) {
    $taskStatic = Join-Path $taskRoot 'frontend\.next\standalone\.next\static'
    New-Item -ItemType Directory -Force $taskStatic | Out-Null
    Copy-Item 'frontend\.next\static\*' -Destination $taskStatic -Recurse -Force
    if (Test-Path 'frontend\public') {
        $taskPublic = Join-Path $taskRoot 'frontend\.next\standalone\public'
        New-Item -ItemType Directory -Force $taskPublic | Out-Null
        Copy-Item 'frontend\public\*' -Destination $taskPublic -Recurse -Force
    }
    $env:HOSTNAME = '127.0.0.1'
    $env:PORT = "$FrontendPort"
    $taskFrontendArgs = @('.next/standalone/server.js')
}
$taskFrontend = Start-Process -FilePath $taskNode -ArgumentList $taskFrontendArgs -WorkingDirectory (Join-Path $taskRoot 'frontend') -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskWork 'frontend.out.log') -RedirectStandardError (Join-Path $taskWork 'frontend.err.log')
@{ backend = $taskBackend.Id; frontend = $taskFrontend.Id; backend_started = $taskBackend.StartTime.ToUniversalTime().ToString('o'); frontend_started = $taskFrontend.StartTime.ToUniversalTime().ToString('o') } | ConvertTo-Json | Set-Content (Join-Path $taskWork 'processes.json') -Encoding utf8
Write-Output "주소: http://127.0.0.1:$FrontendPort"
Write-Output "접속 토큰: $($taskConfig.token)"
Write-Output '종료: ./scripts/stop-local.ps1'
