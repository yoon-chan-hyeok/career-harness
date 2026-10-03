[CmdletBinding(DefaultParameterSetName = 'Login')]
param(
    [Parameter(ParameterSetName = 'Help')]
    [switch]$Help,
    [Parameter(ParameterSetName = 'Status')]
    [switch]$Status
)

$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path -LiteralPath (Split-Path $PSScriptRoot -Parent)).Path
$taskCliRoot = Join-Path $taskRoot 'work\deploy-cli\node_modules\vercel'
$taskCliEntry = Join-Path $taskCliRoot 'dist\vc.js'
$taskCliPackagePath = Join-Path $taskCliRoot 'package.json'
$taskGlobalConfig = Join-Path $taskRoot 'work\vercel-config'

if (-not (Test-Path -LiteralPath $taskCliEntry -PathType Leaf) -or
    -not (Test-Path -LiteralPath $taskCliPackagePath -PathType Leaf)) {
    throw '로컬 Vercel CLI 62.2.0이 없습니다. work/deploy-cli에 준비된 CLI가 필요합니다. 자동 설치는 하지 않습니다.'
}
$taskCliPackage = Get-Content -LiteralPath $taskCliPackagePath -Raw | ConvertFrom-Json
if ($taskCliPackage.name -ne 'vercel' -or $taskCliPackage.version -ne '62.2.0') {
    throw '이 연결 도구는 로컬 Vercel CLI 62.2.0만 사용합니다. 설치된 버전을 확인해 주세요.'
}
$taskNode = Get-Command node -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $taskNode) {
    throw 'Node.js 실행 파일이 없습니다. Vercel CLI 62.2.0에 필요한 Node.js 20 이상을 준비해 주세요.'
}

$taskChildEnvironment = @{
    NO_UPDATE_NOTIFIER = '1'
    VERCEL_TELEMETRY_DISABLED = '1'
    VERCEL_CLI_USE_NATIVE_BINARY = '0'
    CI = '1'
}
$taskSavedEnvironment = @{}
foreach ($taskEnvName in $taskChildEnvironment.Keys) {
    $taskSavedEnvironment[$taskEnvName] = [System.Environment]::GetEnvironmentVariable($taskEnvName, 'Process')
}

try {
    foreach ($taskEnvName in $taskChildEnvironment.Keys) {
        [System.Environment]::SetEnvironmentVariable($taskEnvName, $taskChildEnvironment[$taskEnvName], 'Process')
    }
    $taskCommonArguments = @('--global-config', $taskGlobalConfig, '--cwd', $taskRoot)
    if ($Help) {
        & $taskNode.Source $taskCliEntry login --help @taskCommonArguments
        if ($LASTEXITCODE -ne 0) { throw 'Vercel 로그인 도움말을 읽지 못했습니다.' }
    } elseif ($Status) {
        & $taskNode.Source $taskCliEntry whoami @taskCommonArguments
        if ($LASTEXITCODE -ne 0) { throw 'Vercel 로그인 상태를 확인하지 못했습니다. 연결 승인을 먼저 완료해 주세요.' }
        & $taskNode.Source $taskCliEntry teams list @taskCommonArguments
        if ($LASTEXITCODE -ne 0) { throw 'Vercel 팀 접근 권한을 확인하지 못했습니다.' }
    } else {
        Write-Host '표시되는 Vercel 승인 주소를 브라우저에서 직접 열어 로그인을 완료해 주세요.'
        & $taskNode.Source $taskCliEntry login @taskCommonArguments
        if ($LASTEXITCODE -ne 0) { throw 'Vercel 연결 승인이 완료되지 않았습니다.' }
    }
} finally {
    foreach ($taskEnvName in $taskSavedEnvironment.Keys) {
        if ($null -eq $taskSavedEnvironment[$taskEnvName]) {
            Remove-Item -LiteralPath "Env:$taskEnvName" -ErrorAction SilentlyContinue
        } else {
            [System.Environment]::SetEnvironmentVariable($taskEnvName, $taskSavedEnvironment[$taskEnvName], 'Process')
        }
    }
}
