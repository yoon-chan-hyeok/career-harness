# Vercel + Supabase + FastAPI 실서비스 준비

이 프로젝트의 운영 구성은 Vercel의 Next.js 화면, FastAPI, Supabase PostgreSQL/Auth이다. FastAPI는 기존 별도 컨테이너 구성 또는 [무료 Vercel Hobby 백엔드 준비](VERCEL_FREE_BACKEND.md)의 별도 Python 프로젝트로 배포할 수 있게 준비했다. 실제 계정·비밀키·도메인·외부 서비스 연결이 준비되기 전에는 배포 완료로 판단하지 않는다. Jev는 선택적인 shadow 평가이고 기본 검수 결과를 바꾸지 않는다.

## 준비된 연결

| 부분 | 구현 | 실제 서비스에서 확인할 것 |
|---|---|---|
| 인증 | Supabase 공개 JWKS를 캐시하고 JWT 서명·issuer·audience·만료·subject·authenticated 역할 검증 | 이메일 로그인, 세션 갱신, 로그아웃, 서로 다른 사용자 격리 |
| DB | Supabase URL의 psycopg 3 드라이버 정규화, pool pre-ping, 연결 타임아웃, migration 전용 URL | 실제 PostgreSQL migration 및 SSL 인증서, connection limit |
| 데이터 공개 방지 | Career 테이블 RLS 및 anon/authenticated/PUBLIC 권한 차단 SQL, 운영 readiness 검사 | Supabase Data API로 개인 행을 조회할 수 없는지 |
| 운영 API | liveness/readiness, 요청 크기·빈도 제한, host/CORS 제한, 개인 응답 no-store | HTTPS ingress, 재시작, gateway timeout, 장애 복구 |
| 배포 | non-root Dockerfile, production Compose, Vercel 설정, 환경 예시 | 실제 프로젝트 연결·배포·도메인 |
| 공급자 | HF/Groq/OpenAI 중 선택한 제공자와 Jev의 opt-in 합성 실호출 진단 | 현재 모델 이용 권한, 무료 크레딧·한도 및 청구 설정, 한국어 응답 품질 |
| 백업 | SQLite 및 PostgreSQL Career 테이블 백업, checksum, 빈 대상 복구 | 별도 빈 운영 테스트 DB에서 복구와 readiness |

실제 API 키나 문서 원문을 Git·Vercel public 환경변수·브라우저 번들에 넣지 않는다. 화면은 Supabase Auth만 사용한다. 개인 문서는 Vercel의 같은 출처 `/api` 프록시를 통해 FastAPI로 전달되고, 서버가 검증한 JWT subject로 모든 저장소 쿼리를 제한한다.

로컬 제공자 키 파일과 저장 중 생기는 임시 파일은 `.dockerignore`에서도 제외한다. `python scripts/check_privacy.py`는 Git에 추적된 파일과 **미추적 등록 후보**를 함께 검사한다. 개인 원본·화면 캡처·DB 부속 파일·키 파일을 제외하고 공개 회귀 fixture의 합성 출처, Docker/Vercel 마지막 보호 규칙을 확인한다. 원본 과거 사례와 개인 작성전략은 로컬에서 비공개로 보존한다. 검사는 모든 개인정보를 자동 식별하는 도구가 아니므로 새로운 공개 파일의 내용 검토도 필요하다.

## 1. Supabase

Career Harness 전용 프로젝트를 준비한다. 기존 다른 서비스가 사용하는 DB에 이 배포 예시를 그대로 적용하지 않는다.

1. Auth에서 사용할 이메일 사용자를 준비하고 필요한 redirect URL을 실제 Vercel 도메인으로 설정한다. 개인 서비스라면 자체 회원가입을 끄고 사용자 UUID를 `CAREER_ALLOWED_USER_IDS`에 등록한다.
2. Auth Signing Keys에 ES256 또는 RS256 서명 키를 설정한다. 이 백엔드는 과거 공유 secret HS256 방식으로 자동 fallback하지 않는다. 공개 JWKS와 issuer는 해당 프로젝트 HTTPS origin에서만 가져온다.
3. Dashboard의 Connect에서 **Direct connection** 또는 IPv4가 필요한 경우 **Session pooler** URL을 가져온다. 비밀번호의 `@`, `:`, `/` 등은 URL 인코딩한다. runtime `DATABASE_URL`과 release 전용 `DATABASE_MIGRATION_URL`을 서버에 저장한다.
4. DB SSL 설정에서 인증서를 내려받아 서버 `/run/secrets/supabase-ca.crt`에 read-only로 공급하고 `sslmode=verify-full&sslrootcert=/run/secrets/supabase-ca.crt`를 사용한다. 코드의 최소 TLS 검사는 `require`도 허용하지만 예시는 호스트·CA까지 확인한다.
5. Auth publishable key는 `SUPABASE_PUBLISHABLE_KEY`에 저장한다. 이것은 브라우저 사용 가능한 키이며 `/api/auth/config`로 공급된다. `service_role`/`sb_secret_` 키는 이 설정에 넣을 수 없다. DB 비밀번호는 서버만 사용한다.

장시간 살아 있는 컨테이너에서는 direct/session 연결을 기본으로 한다. Transaction pooler가 꼭 필요한 경우 runtime만 `DATABASE_POOL_MODE=transaction`으로 설정해 prepared statement를 끄고 migration은 direct/session 연결을 사용한다. 서비스의 connection limit에 맞춰 `DATABASE_POOL_SIZE × replicas`와 `DATABASE_MAX_OVERFLOW`를 함께 계산한다.

Supabase의 새 테이블 Data API 자동 공개 기본값은 변경 중이다. 이 앱은 직접 PostgreSQL 연결을 사용하고 브라우저의 Career 테이블 접근은 차단하므로, 새 기본값에 기대어 보호 SQL을 생략하거나 `anon`/`authenticated`에 테이블 권한을 추가하지 않는다. 배포 시 실제 테이블의 권한과 RLS를 계속 검사한다. [Supabase 자동 공개 변경 안내](https://supabase.com/changelog/45329-breaking-change-tables-not-exposed-to-data-and-graphql-api-automatically).

## 2. 백엔드 컨테이너

`deploy/backend.env.example`을 참고해 서버 secret manager에 실제 값을 등록한다. `CAREER_ENV=production`, `AUTH_MODE=supabase`, `AUTH_TOKENS={}`를 유지한다. production/staging에서는 개인 로컬 토큰 인증을 허용하지 않는다.

컨테이너 image를 빌드하고, 트래픽을 받기 전에 같은 이미지와 환경으로 한 번 실행한다.

```sh
python -m alembic upgrade head
python scripts/secure_supabase.py --apply
python scripts/deployment_preflight.py --check-database --check-public-keys
```

`secure_supabase.py`는 기본 실행에서 변경하지 않고 SQL 위치만 보여 준다. `--apply`는 `deploy/supabase-security.sql`의 검토된 내용을 원자적으로 적용한다. Career 테이블의 RLS를 켜고 PUBLIC/anon/authenticated의 직접 테이블 권한을 제거한다. 원문·사실·문서 데이터는 변경하지 않는다. 서버 DB owner 연결은 계속 동작하고 브라우저 사용자는 DB를 직접 읽지 못한다. 새 migration으로 테이블을 추가하면 보호 SQL도 업데이트해야 하며 `/ready`가 누락을 잡는다.

Docker Compose를 운영 서버에서 사용하는 경우 `.env.production`에 실제 설정을 넣고 DB CA의 host 경로를 `DATABASE_SSL_ROOT_CERT`로 지정한다. `compose.production.yaml`은 8000 포트를 loopback에만 바인딩한다. 앞단 HTTPS reverse proxy 또는 managed container ingress가 외부 트래픽을 처리해야 한다. `CAREER_ALLOWED_HOSTS`에는 실제 API 호스트와 내부 health probe 호스트만 넣는다.

```sh
docker compose -f compose.production.yaml build
docker compose -f compose.production.yaml up -d
```

Managed container host에서는 Dockerfile을 사용하고 같은 환경·CA 파일을 공급한다. 프로세스 entrypoint는 설정을 먼저 검증한 뒤 실행한다. migration을 여러 replica가 동시에 실행하지 않도록 `RUN_MIGRATIONS=0`이 기본이다. release command가 migration과 보호 SQL을 담당한다. 이미 검토한 단일 local Compose는 `RUN_MIGRATIONS=1`을 사용한다.

## 3. Vercel

Vercel 프로젝트의 Root Directory를 `frontend`로 지정한다. Next.js framework와 `frontend/vercel.json`의 build/install 설정을 사용한다. Vercel의 **서버 환경변수** `BACKEND_URL`에 배포된 API HTTPS origin을 넣고 새 build/deploy를 만든다. 이 값은 rewrite 구성에 사용되므로 바꾼 뒤 재배포가 필요하다.

위 Root Directory는 Git 저장소를 연결하는 Dashboard 방식 기준이다. 로컬 CLI는 실제 앱 루트와 그 안의 `frontend`를 각각 두 프로젝트로 연결하고 명시적인 `--cwd`를 사용한다. 이 채팅의 상위 작업 폴더를 배포하지 않는다. 두 프로젝트의 경로와 연결 확인 순서는 [무료 Vercel 백엔드 안내](VERCEL_FREE_BACKEND.md#정확한-로컬-배포-루트와-계정-연결)에 있다. 각 `.vercel/project.json`을 확인해 화면이 상위 백엔드 프로젝트에 연결되지 않도록 한다.

**새 Vercel 프로젝트의 첫 배포는 일반 `vercel deploy`여도 production이다.** 초기 배포를 preview로 취급하지 않는다. 초기 production build를 도메인에 연결하지 않으려면 설치된 CLI 옵션을 확인한 뒤 `vercel deploy --prod --skip-domain`으로 준비하고, 실제 HTTPS·인증·저장·모델 호출을 검증한 다음 `promote` 또는 도메인 연결을 진행한다. 플러그인 설치나 MCP 로그인은 로컬 CLI 로그인·프로젝트 연결·실제 배포 완료를 의미하지 않는다. 현재 노출된 `deploy_to_vercel`에는 파일/경로의 명시적 입력 계약이 없어 추정한 파라미터로 호출하지 않았으며, 팀 목록이 비어 있으면 계정과 해당 팀의 접근 권한부터 확인한다. [공식 CLI 첫 배포 안내](https://vercel.com/docs/cli/deploying-from-cli), [MCP 팀 권한 안내](https://vercel.com/docs/agent-resources/vercel-mcp/tools).

`DATABASE_URL`, `HF_TOKEN`, `GROQ_API_KEY`, `OPENAI_API_KEY`, `JEV_API_KEY`, Supabase service-role key는 Vercel frontend에 필요하지 않다. 이 비밀값은 백엔드 secret manager에만 저장하고 `NEXT_PUBLIC_*`에 넣지 않는다. Supabase public project configuration은 백엔드가 검증해서 화면에 제공한다. 화면과 API proxy가 같은 origin이면 `CAREER_CORS_ORIGINS`는 비워 둔다. API를 별도 브라우저 origin에서 직접 호출하는 구성을 선택한 경우에만 실제 HTTPS 화면 origin을 정확히 지정한다.

화면 로그인부터 문서 작성까지 여러 단계의 AI 요청을 포함한다. 각 공급자 timeout과 서비스/프록시 timeout을 맞추고 실제 지원서에서 완료·실패·재시도 상태를 확인한다. Vercel의 function/rewrite 제한을 넘는 작업을 단순히 더 큰 timeout 하나로 해결했다고 판단하지 않는다. 여러 replica를 사용하는 경우 현재 단일 프로세스 요청 제한에 더해 ingress의 공유 rate limit을 설정한다.

## 4. 공급자 연결과 진단

아래 기본 명령은 환경 구성만 검사하며 네트워크 요청이나 DB 쓰기를 하지 않는다. 결과는 설정 값·연결 URL·비밀키·문서 내용을 출력하지 않는다.

```sh
python scripts/deployment_preflight.py
```

각 옵션은 독립적으로 선택한다.

```sh
# 읽기 전용 DB·migration·pgvector·개인 테이블 보호 검사
python scripts/deployment_preflight.py --check-database
# 비밀키 없이 해당 프로젝트의 공개 서명 키만 조회
python scripts/deployment_preflight.py --check-public-keys
# 선택한 HF/Groq/OpenAI 제공자에 합성 입력 호출. 무료 한도 사용 또는 과금 가능.
python scripts/deployment_preflight.py --live-ai
# 별도 OpenAI·Jev 직접 호출. 과금이 발생할 수 있음.
python scripts/deployment_preflight.py --live-openai --live-jev
```

사용자 본인의 HF 계정이 있다. [무료 제공자 연결 안내](FREE_PROVIDER_SETUP.md)에 따라 `CAREER_LLM_PROVIDER=huggingface`, `HF_TOKEN`, `HF_MODEL=openai/gpt-oss-120b:fireworks-ai`를 백엔드에 설정한다. 계정의 무료 크레딧과 청구 설정을 직접 확인한 뒤에만 `HF_FREE_ONLY_CONFIRMED=1`을 설정한다. Groq Free 계정은 `CAREER_LLM_PROVIDER=groq`, `GROQ_API_KEY`, `GROQ_MODEL=openai/gpt-oss-120b`, `GROQ_FREE_ONLY_CONFIRMED=1`로 선택한다. 확인 값은 사용자의 계정 확인 기록이며 제공자 청구 상태의 원격 검증이나 요금 차단 장치가 아니다. 무료 한도 소진 후 다른 제공자로 자동 전환하지 않으며 `CAREER_LLM_PROVIDER=none`으로 직접 작성을 이어갈 수 있다. `CAREER_REQUIRE_AI=1`을 사용하는 운영 환경은 직접 작성 전환 계획에 맞게 이 설정도 검토해야 한다.

공통 생성 설정은 `CAREER_LLM_TIMEOUT_SECONDS`, `CAREER_LLM_MAX_OUTPUT_TOKENS`, `CAREER_LLM_SMALL_MODEL`, `CAREER_LLM_STAGE_POLICIES`, `CAREER_LLM_PRICING_JSON`이다. 생략하면 기존 `OPENAI_*` 설정과 호환한다. 예시의 출력 한도는 4096이며 실제 무료 계정 한도와 요청 크기에 맞춰 조정한다. 가격 정보가 없으면 비용을 0으로 확정하지 않는다. HF/Groq 생성 연결만으로 OpenAI 웹 조사나 1536차원 임베딩도 연결되지 않는다.

OpenAI 상용 API는 `CAREER_LLM_PROVIDER=openai`, `OPENAI_API_KEY`와 명시적인 `OPENAI_MODEL`이 있어야 한다. 공개 gpt-oss 경로와 별개이며 무료 상용 OpenAI API를 확인한 것으로 표시하지 않는다. `selected_ai.live_verified=true`는 합성 요청의 스키마가 처리됐다는 의미이고, `status=ok`여야 기대한 응답까지 확인한 것이다. CLI 결과는 화면의 연결 검사 기록을 갱신하지 않는다. 실제 채용 자료 품질이나 전체 업무 흐름 검증은 별도로 수행한다.

Jev는 `JEV_API_KEY`, `JEV_MODEL`, 선택적 `JEV_SHADOW_ENABLED=1`로 활성화한다. 공식 무료 제공 조건과 실제 이용 권한이 확인되지 않아 기본값은 꺼짐이다. 실제 어댑터는 고정된 공식 Typesafe endpoint에만 자격증명을 보내고 redirect를 따라가지 않는다. 네트워크 실패가 기본 검수를 중단하거나 shadow 결과를 자동 승격하지 않는다.

## 5. 백업과 복구

백업은 개인자료 전체를 포함한다. 기본 경로는 Git에서 제외하는 `work/backups`다. 운영에서는 서버 전용 저장소에서 암호화·접근 제한·보존 기간을 설정하고 DB와 분리해 보관한다. PostgreSQL용 `pg_dump`/`pg_restore`는 대상 서버와 호환되는 major version의 client tool이 필요하다. 비밀번호는 CLI 인수에 넣지 않고 자식 프로세스 환경으로만 전달한다.

```sh
python scripts/database_backup.py backup
python scripts/database_backup.py restore work/backups/<backup>.backup
```

두 번째 명령은 checksum 확인과 복구 미리보기만 한다. 복구용 **별도 빈 대상 DB**의 `DATABASE_URL`을 설정하고 서비스 트래픽을 차단한 뒤 아래 명령으로 실행한다. 기존 개인 행이나 관련 없는 테이블이 있는 대상은 거절한다. SQLite↔PostgreSQL 변환 도구가 아니며 포맷이 같은 DB로 복구한다.

```sh
python scripts/database_backup.py restore work/backups/<backup>.backup --execute --confirm-empty-target
python scripts/secure_supabase.py --apply
python scripts/deployment_preflight.py --check-database
```

PostgreSQL 복구 대상은 pgvector extension과 빈 schema migration을 먼저 준비한다. 백업은 Career 테이블만 포함하고 Supabase Auth 사용자나 외부 저장소는 포함하지 않는다. Auth 계정 복구/유지, CA·환경 설정과 DB snapshot을 함께 검증해야 실제 재난 복구가 된다.

## 출시 판정

공개 `/health`는 프로세스 liveness이고 `/ready`는 실제 DB, migration head, pgvector 및 운영 개인 테이블 보호와 인증 설정을 검사한다. 공급자 항목의 `configured`는 실호출 성공을 의미하지 않는다. 성공한 화면의 **연결 검사**가 없으면 `live_verified=false`로 표시되며, 검사를 통과한 현재 제공자·모델·키·무료 확인 조합에는 성공 시각이 표시된다. 설정을 바꾸거나 연결 검사에 실패하면 이 기록은 해제된다. CLI의 opt-in 실호출 진단은 별도 출력으로만 확인한다.

출시 전 실제 Supabase/Vercel/컨테이너 연결, 로그인 갱신, 두 사용자 격리, JD→근거→승인→작성→검수→제출확정→handoff, 공급자 실패 및 복구, 백업 복구, HTTPS/로그 비밀정보 제외를 검증한다. 지금 작성된 연결 코드와 local 테스트만으로 이 외부 검증을 완료했다고 표시하지 않는다.

모델 비교 실험과 Jev 비교의 완료 여부는 [사용자 결정](USER_DECISIONS.md)에 따라 출시 필수 조건에서 제외한다. 위 기능·보안·실제 연결 검사는 유지한다. 비교를 생략한 상태에서 성능 우위나 실제 모델 품질 검증 완료를 주장하지 않는다.

## 확인한 공식 자료

- [Supabase JWT 검증 및 JWKS](https://supabase.com/docs/guides/auth/jwts)
- [Supabase JWT signing keys](https://supabase.com/docs/guides/auth/signing-keys)
- [Supabase DB direct/session/transaction 연결](https://supabase.com/docs/guides/database/connecting-to-postgres)
- [Supabase SSL 연결](https://supabase.com/docs/guides/database/connecting-to-postgres#connecting-with-ssl)
- [Supabase RLS와 테이블 권한](https://supabase.com/docs/guides/database/postgres/row-level-security)
- [PyJWT 서명·필수 claim·issuer·audience 검증](https://pyjwt.readthedocs.io/en/stable/usage.html)
- [SQLAlchemy pool pre-ping](https://docs.sqlalchemy.org/en/20/core/pooling.html#disconnect-handling-pessimistic)
- [Vercel 프로젝트 환경변수](https://vercel.com/docs/environment-variables)
- [Vercel functions 제한](https://vercel.com/docs/functions/limitations)
- [Typesafe Jev 공식 API 계약](https://docs.typesafe.ai/api)
- [PostgreSQL pg_dump 아카이브·대상 테이블·복구 의존성](https://www.postgresql.org/docs/current/app-pgdump.html)
