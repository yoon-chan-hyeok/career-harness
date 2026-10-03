$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path $PSScriptRoot -Parent
$taskConfig = Get-Content (Join-Path $taskRoot 'work\processes.json') -Raw | ConvertFrom-Json
foreach ($taskName in @('backend','frontend')) {
    $taskProcess = Get-Process -Id $taskConfig.$taskName -ErrorAction SilentlyContinue
    $taskTimeField = $taskName + '_started'
    if ($taskProcess -and $taskProcess.StartTime.ToUniversalTime().Ticks -eq ([datetime]$taskConfig.$taskTimeField).ToUniversalTime().Ticks) {
        # Include only children of this verified server process; Next dev forks a worker.
        taskkill /PID $taskProcess.Id /T /F
        if ($LASTEXITCODE -ne 0) { throw "$taskName 서버 종료에 실패했습니다. 동일 사용자 권한으로 다시 실행하세요." }
    }
}
