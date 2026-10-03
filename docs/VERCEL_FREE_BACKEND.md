# Vercel Hobby에서 FastAPI 백엔드 준비

개인·비상업 서비스의 무료 경로로 **별도 Vercel FastAPI 프로젝트 + Vercel Next.js 프로젝트 + Supabase Free**를 준비했다. 루트 `app.py`, `vercel.json`, `.vercelignore`는 백엔드 프로젝트용이고 화면 프로젝트의 Root Directory는 계속 `frontend`다. 이 설정을 추가한 것은 실제 프로젝트 생성·배포·인증·모델 호출 성공을 뜻하지 않는다. 유료 플랜, 크레딧 구매, 자동 유료 제공자 전환은 포함하지 않는다.

## 백엔드가 시작되는 방식

`app.py`는 DB 엔진을 import하기 전에 `career.serverless.prepare_serverless_environment()`를 실행한다. 이 경로는 `CAREER_ENV=production` 또는 `staging`, Supabase 인증, PostgreSQL `sslmode=verify-full`, 공개 CA 공급을 요구한다. 로컬 인증·SQLite·TLS 완화·자동 migration을 허용하지 않는다. 기존 정상 로컬 실행은 `career.api:app`를 사용하므로 이 별도 진입점으로 바뀌지 않는다.

`CAREER_DATABASE_CA_PEM`에 Supabase Dashboard에서 받은 **공개 DB CA 인증서**를 실제 줄바꿈이 있는 PEM으로 넣는다. 공개 인증서만 허용하고 private key가 섞이면 시작에 실패한다. 프로세스 전용 임시 디렉터리에 trust 파일을 쓰고 `DATABASE_URL`의 `sslrootcert`만 그 경로로 설정한다. URL의 호스트·비밀번호·`verify-full`은 유지한다. 업로드된 `.env`를 읽지 않으며 로컬 제공자 파일도 사용하지 않는다. CA 값·DB URL·키는 로그나 응답으로 출력하지 않는다. 임시 파일은 문서·키 저장소가 아니다.

환경은 `deploy/vercel-backend.env.example`을 참고한다. 실제 DB 비밀번호·HF 키는 **백엔드 프로젝트의 encrypted 환경변수**에만 넣고 `NEXT_PUBLIC_*`에 넣지 않는다. 개인 서비스에서는 `CAREER_ALLOWED_USER_IDS`에 본인의 확인된 UUID를 등록하고 Supabase 공개 가입을 끈다. 사용자 격리 인수 검사 동안에만 별도 QA 사용자의 UUID를 잠시 추가할 수 있으며 검사가 끝나면 소유자 UUID만 유지한다. JWT 서명·issuer·audience·subject 검증 및 기존 Data API 권한 차단/RLS 검사는 그대로 유지된다. `CAREER_ALLOWED_HOSTS`는 실제 백엔드 도메인을 명시하며, 플랫폼의 `VERCEL_URL`이 있으면 그 정확한 단일 호스트만 추가한다.

DB 기본 연결은 transaction pooler, pool size 1, overflow 0이다. 이 모드의 기존 DB 어댑터는 psycopg prepared statement를 끈다. pool size는 최대 2, overflow는 0으로 제한한다. 인스턴스가 늘면 전체 연결 수도 늘기 때문에 실제 Supabase pooler 한도는 별도로 확인한다. migration은 direct/session 연결로 별도 release 단계에서 한 번 실행한다.

## 배포할 파일과 실제 연결 순서

루트 `.vercelignore`는 처음부터 전체를 제외하고 런타임 Python 코드, `pyproject.toml`, 진입점·설정, migration metadata, 합성 fixture만 허용한다. 프런트엔드·테스트·work·private_input·DB·백업·로컬 키·환경 파일은 업로드 대상이 아니다. `frontend/.vercelignore`도 별도 화면 프로젝트에서 개인 파일을 제외한다. `scripts/check_privacy.py`는 양쪽 제외 파일의 마지막 보호 규칙이 삭제되거나 재포함으로 덮였는지 검사한다. Python function `excludeFiles`는 bundle에서도 개인 파일과 불필요한 파일을 추가로 제외한다.

실제 실행 순서는 다음과 같다.

1. 사용자가 선택한 Supabase 조직의 비용을 조회하고 무료 비용임을 확인한 뒤 전용 프로젝트를 만든다. Auth·DB CA·사용자 UUID를 준비하고 무료 플랜을 유지한다.
2. 별도 release 환경에서 실제 direct/session DB URL과 CA 파일 경로로 `alembic upgrade head`, `scripts/secure_supabase.py --apply`, 읽기 전용 DB preflight를 실행한다. Vercel build/콜드스타트에서 이 작업을 실행하지 않는다. 이 문서는 migration을 실행하지 않았다.
3. 실제 Vercel 계정의 확인된 Hobby 범위에서 백엔드 프로젝트를 아래의 정확한 루트에 연결한다. FastAPI framework와 루트 `vercel.json`을 사용하고 backend-only 환경변수를 공급한다. 필요한 CLI 버전·명령은 공식 문서와 설치된 CLI의 `--help`로 확인한다. 연결된 MCP OAuth와 로컬 CLI 로그인은 별개다.
4. `python scripts/check_privacy.py`를 통과하고 CLI의 실제 업로드 목록과 함수 bundle에서 개인 파일이 없는지 확인한 뒤 초기 백엔드 배포를 검증한다. **새 프로젝트의 첫 `vercel deploy`는 `--prod`가 없어도 production 배포**이므로 이를 preview라고 가정하지 않는다. 초기 production build를 도메인에 연결하지 않으려면 설치된 CLI의 옵션을 확인하고 `vercel deploy --prod --skip-domain`을 사용한다. 생성된 HTTPS 주소의 `/health`, `/ready`, 인증 없는 개인 API 차단을 확인한 뒤 실제 도메인 연결 또는 `promote`를 진행한다. 배포 보호를 임의로 끄지 않는다. 기존 프로젝트의 이후 일반 배포는 preview지만 실제 반환된 target과 상태를 확인한다.
5. 화면은 별도 프로젝트, Root Directory `frontend`로 배포한다. 기존 서버 환경변수 `BACKEND_URL`에 실제 HTTPS 백엔드 origin을 넣는다. DB·HF 키는 화면 프로젝트에 복사하지 않는다. Backend와 frontend preview 보호 설정이 프록시를 막으면 플랫폼의 승인된 접근 방법으로 처리한다.
6. Supabase 로그인·세션 갱신·사용자 격리와 JD→근거→승인→자소서/레쥬메→검수→저장을 실제로 확인한다. 개인 데이터 seed/import는 DB를 통해 소유자 인증 하에 실행하며 배포 소스에 넣지 않는다.

## 정확한 로컬 배포 루트와 계정 연결

이 채팅의 작업 디렉터리는 실제 앱 루트의 상위 디렉터리다. 상위 디렉터리에서 경로 없이 `vercel`을 실행하거나 전체 폴더를 업로드하지 않는다. CLI를 사용할 때는 두 프로젝트를 각각 연결하고 모든 명령에 정확한 `--cwd`를 지정한다.

```powershell
$careerBackendRoot = 'C:\Users\ych13\Documents\Codex\2026-09-29\codex-master-prompt-md\outputs\career_harness_codex_one_shot_v2_2_FINAL'
$careerFrontendRoot = Join-Path $careerBackendRoot 'frontend'
# 도움말은 실제 로그인을 시작하지 않는다.
& "$careerBackendRoot/scripts/connect-vercel.ps1" -Help
# 승인 주소를 수동으로 여는 device login. 사용자가 브라우저에서 승인한다.
& "$careerBackendRoot/scripts/connect-vercel.ps1"
# 승인 완료 후 계정과 접근 가능한 팀을 읽기 전용으로 확인한다.
& "$careerBackendRoot/scripts/connect-vercel.ps1" -Status
```

`connect-vercel.ps1`은 준비된 `work/deploy-cli`의 **Vercel CLI 62.2.0**만 사용한다. CLI가 없거나 버전이 다르면 명확히 실패하며 자동 설치·프로젝트 연결·배포·결제는 하지 않는다. 설정·인증 위치는 `work/vercel-config`, 모든 호출의 `--cwd`는 위 백엔드 루트다. 기본 동작은 수동 device login이고 `-Help`와 `-Status`는 서로 다른 모드다. `-Status`도 로그인이 필요한 계정 조회이며 승인 대기 상태에서는 완료로 표시하지 않는다.

설치 소스와 도움말에서 확인한 `NO_UPDATE_NOTIFIER=1`, `VERCEL_TELEMETRY_DISABLED=1`, `VERCEL_CLI_USE_NATIVE_BINARY=0`, `CI=1`을 자식 CLI 호출 동안만 적용하고 `finally`에서 기존 프로세스 환경을 복원한다. `CI=1`은 Codex에서 브라우저 자동 실행을 막는다. telemetry 전송을 꺼도 CLI device/session JSON은 생성될 수 있으므로 workspace 전용 전역 설정 경로를 함께 사용한다. `vercel deploy --dry`도 인증을 요구하므로 로그인 없이 실제 업로드 목록을 검증했다고 판단하지 않는다. **로그인에 `--debug`를 추가하지 않는다.** CLI 62.2.0의 device flow 구현은 debug 모드에서 access token 응답 원문을 출력한다. 인증 파일과 출력에 포함될 수 있는 개인 정보는 기존 `work/**` 업로드·Git 제외 범위로 보호한다.

로그인 승인과 계정·Hobby 팀 확인 후 백엔드는 `$careerBackendRoot`, 화면은 `$careerFrontendRoot`에서 별도로 `vercel link`한다. 실제 확인한 팀을 `--scope`로 지정하고, 각 `.vercel/project.json`의 `orgId`와 `projectId`가 의도한 두 프로젝트인지 확인한다. 화면에서 상위 백엔드의 링크를 상속한 채 배포하지 않는다. CLI가 화면 폴더만 업로드하는 경우 그 업로드 루트가 프로젝트 루트이며, Git 저장소 전체를 연결하는 Dashboard 방식의 Root Directory `frontend`와 혼동하지 않는다. 키는 채팅이나 명령행 인수에 넣지 않는다.

2026-10-03 확인 시 연결된 Vercel 도구는 `list_teams`에서 접근 가능한 팀을 반환하지 않았고, `deploy_to_vercel`의 노출된 입력 스키마에는 파일 목록·로컬 경로·배포 대상이 명시되지 않았다. 이 도구에 추정한 파라미터를 넣거나 빈 객체로 배포를 시도하지 않았다. 최신 공식 MCP 문서는 별도 `create_deployment`와 `upload_file` 도구를 설명하지만 현재 연결에서 이 도구들이 노출된 것은 아니다. 문서 검색의 오래된 조각만으로 현재 연결의 쓰기 권한이나 파일 전송 계약을 확정하지 않는다. 팀 목록이 비어 있다는 사실도 계정의 플랜이나 팀 부재를 증명하지 않는다. 공식 안내대로 올바른 계정 로그인과 원하는 팀의 연결 권한을 확인해야 한다.

현재의 지원 가능한 파일 배포 경로는 인증된 공식 CLI다. 플러그인 로그인 정보를 추출해서 CLI 자격증명으로 재사용하지 않는다. 계정 확인·팀 권한·Supabase 설정이 준비된 뒤 위 배포 순서를 실행하고 실제 deployment URL/ID, target, READY 상태를 기록해야 배포 완료로 판정한다.

## 무료 운영의 한계

현재 공식 문서상 Hobby Fluid Compute 함수의 최대 요청 실행 시간은 300초이고, 루트 설정도 `maxDuration=300`이다. 앱은 요청 안에서 AI 작업을 수행하므로 실제 전체 작업이 제한 안에 끝나는지 확인해야 한다. `EXECUTION_TIMEOUT_SECONDS=330`은 종료된 작업의 상태 복구 기준이며 플랫폼 실행 시간을 늘리지 않는다. 무한 백그라운드 작업이나 항상 켜진 프로세스를 제공하지 않는다. 프런트엔드 rewrite 경로의 실제 timeout도 따로 확인해야 한다.

Function payload의 플랫폼 한도는 4.5MB다. 백엔드 요청을 그보다 작은 **4,000,000 bytes**로 제한한다. 이 제한은 화면의 `/api` 프록시를 거치는 요청에도 적용되는 계약이며 대용량 문서는 작은 단위로 나누거나 인증된 별도 업로드 설계가 필요하다. 존재하지 않는 `API_PROXY_*` 환경변수로 플랫폼 한도나 timeout을 바꿀 수 있다고 안내하지 않는다. 표준 Python bundle 한도는 500MB이며 실제 remote build 결과로 최종 확인한다. 유료 Large Functions나 확장 실행시간은 사용하지 않는다.

운영 제공자 설정은 서버 환경변수 기반의 읽기 전용이다. `/api/providers/check`는 로컬 소유자용 검사이고, CLI opt-in 합성 preflight의 출력은 화면의 durable `live_verified` 기록을 갱신하지 않는다. 서버리스 인스턴스 메모리도 인스턴스 간 공유·영속 저장소가 아니다. 화면의 연결 표시만으로 운영 실호출·청구 상태·계속 사용 가능함을 보증하지 않는다. 실제 응답과 기록을 별도로 확인한다.

Supabase Free는 비활성 기간에 일시 정지될 수 있고 별도 백업도 필요하다. 로컬 DB 파일이나 임시 디렉터리에 운영 데이터를 저장하지 않는다. HF 무료 크레딧과 Vercel/Supabase 무료 할당량은 무제한이 아니며 한도 소진 후 직접 작성·재시도 안내를 유지한다.

## 공식 근거

- [FastAPI 진입점과 단일 Python Function](https://vercel.com/docs/frameworks/backend/fastapi)
- [Python runtime·의존성·bundle 제외](https://vercel.com/docs/functions/runtimes/python)
- [Hobby 요청 실행시간](https://vercel.com/docs/functions/configuring-functions/duration)
- [Function payload 제한](https://vercel.com/docs/functions/limitations)
- [개인·비상업 Hobby 조건](https://vercel.com/docs/plans/hobby)
- [.vercelignore allowlist](https://vercel.com/docs/deployments/vercel-ignore)
- [CLI 배포 경로·첫 배포의 production target·staged production](https://vercel.com/docs/cli/deploying-from-cli)
- [CLI의 정확한 작업 경로·scope·인증](https://vercel.com/docs/cli/global-options)
- [CLI 로그인](https://vercel.com/docs/cli/login)
- [MCP 로그인과 팀 접근 권한](https://vercel.com/docs/agent-resources/vercel-mcp/tools)
- [최신 MCP 배포 도구 계약](https://vercel.com/docs/agent-resources/vercel-mcp/tools/deployments)
- [Supabase DB/pooler/TLS 연결](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase 무료 플랜](https://supabase.com/pricing)

Vercel Services의 최신 `services` 구성이 모든 플랜 Beta로 존재하지만, 이번 구현은 안정적인 별도 Python 프로젝트를 선택했다. 이전 `experimentalServices` 스킬 예제를 현재 서비스 설정으로 그대로 복사하지 않는다. [현재 Services 문서](https://vercel.com/docs/services).
