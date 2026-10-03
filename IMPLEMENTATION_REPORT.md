# 구현·검증 현황

> 2026-10-03 후속 코드 감사 정정: 기존 핵심 기능과 아래 검사 기록은 유지하지만, AI 이력서 분량 옵션·PostgreSQL 근거 검색·전체 요청 시간·긴 입력 사전 제한에 추가 보완을 발견했다. 계정 연결만 남은 상태가 아니다. 이번 감사는 수정/전체 검사 재실행을 하지 않았다. [추가 작업·업그레이드 감사](docs/REMAINING_WORK_AND_UPGRADES.md)가 현재 남은 작업의 기준이다.

2026-10-03. **Hugging Face/Groq 생성 연결 코드, 레쥬메 작성·검토·보관, 역할별 지시문과 개인 설정 화면의 로컬 검증을 마쳤다. 앱은 실행 중이다. 실제 추론 토큰과 공개 서비스 배포는 아직 연결하지 않았다.**

## 현재 사용자 범위

본인이 사용하는 취업 서비스이자 개인 포트폴리오가 목표다. 최신 직접 요청은 [USER_DECISIONS](docs/USER_DECISIONS.md)에 기록했다. 비교·성능 개선·업그레이드 실험은 이번 범위와 출시 조건에서 제외한다. 기존 평가 코드는 보존한다. 사실·본인 역할·출처 검수, 인증·계정 격리, 실패 처리와 복구 검사는 유지한다. 설계 의도·RAG·Jev 설명 페이지는 이후 작업이다.

## 이번에 마친 코드

- HF 공식 router와 Groq Chat Completions를 같은 Workflow에 연결했다. 직무 분석·전략·대화·자소서·레쥬메·검수가 선택한 제공자를 사용한다. 역할 25개의 자료 경계·작업·출력 지시문과 버전을 구분했다.
- 개인 소유자는 설정 → AI 연결에서 토큰을 비공개로 저장하고 짧은 합성 한국어 요청으로 연결을 확인한다. 토큰은 브라우저 저장소·응답·trace에 넣지 않는다. 운영은 백엔드 환경변수로 관리한다.
- 키 등록과 실제 응답 확인을 구별한다. 401/402/429·잘린 응답·스키마 오류에서 기존 자료를 유지하고 실패를 표시한다. 재시도·redirect·다른 유료 제공자 전환을 자동으로 하지 않는다.
- 레쥬메는 섹션·bullet·근거·Claim 연결, 검수·승인·버전·보관·마스터 재사용 및 HTML/Markdown 흐름에 포함한다. HF 어댑터로 자소서와 레쥬메가 실제 제품 Workflow와 DB를 거치는 검사는 합성 HTTP 응답으로 통과했다.
- 공식 Jev shadow의 숫자 확신도를 HTTP 응답부터 영속 PromptRun까지 연결했다. 잘못된 값이나 shadow 장애는 기본 작성을 바꾸지 않는다. 무료 Jev 잔액은 확인하지 못했고 선택 연결로 유지한다.
- 제공자 설정 파일과 임시 파일을 Git·Docker build context에서 제외하고 개인정보 검사로 확인한다.
- 별도 Vercel FastAPI 백엔드 프로젝트를 준비했다. 공개 CA 공급과 `verify-full`·Supabase 인증·PostgreSQL 검증, 4MB 요청·작은 DB pool·migration 미실행, 키/DB/개인자료 업로드 제외를 적용했다. Vercel 프런트엔드는 정확한 HTTPS 백엔드 주소가 없으면 빌드가 실패하도록 검사한다.

## 전체 구현

Next.js 대화·오른쪽 문서 보관함·경험 정리 → 인증 REST/읽기 전용 MCP → FastAPI Workflow → 버전 Artifact·Truth·검색·검수·승인 구조다. 공고/JD 분석, 사실·표현 분리, 근거 연결, 전략/문항 역할 승인, 자소서/레쥬메 작성, 병렬 사실/채용 관점 검수, 구조 교정·부분 수정, 불변 제출본, 별도 실제 제출 확인, 면접 재료, 전형 결과·보수적 회고를 구현했다. 추가 기준 6종은 원본·해시·적용 범위를 유지하며 예시 사실을 개인 근거로 주입하지 않는다.

Supabase 인증·세션 갱신·RLS, Vercel/backend 설정, 운영 guards/readiness, 백업 복구와 읽기 전용 MCP가 준비돼 있다. 역할은 중앙 Workflow 안에서 제어하며 자료·승인·상태의 기준은 버전 Artifact다.

## 현재 검증

- Python **281 통과 / 2 미실행**: 실제 PostgreSQL/pgvector·RLS 환경이 없다. 결과는 `work/free-service-tests.xml`이다.
- Ruff·Pyright 0 오류. 프런트엔드 lint·TypeScript, 로그인 검사 **4개**·배포 설정 검사 **4개**, 새 Next.js **15.5.26 production/standalone build** 통과.
- 실제 SQLite **0008 head**, `alembic check` 변경 없음. 마이그레이션 왕복·이전 검사 통과.
- 정상 개인 계정의 로컬 UI·AI 설정을 확인했다. 3000/8000 및 `/health`·`/ready` 정상, 브라우저 경고·오류 없음. 현재 생성 제공자: **none**, 실제 연결 확인: **False**.
- 합성 HTTP로 HF/Groq 공식 요청 형식, 로컬 스키마 검증, 사용량·hash·역할 버전, 장애 격리, 자소서/레쥬메 저장과 Jev 확신도 영속화를 확인했다. 외부 모델을 호출한 검사로 확대하지 않는다.
- 서버리스 검사 24개를 추가했다. 실제 필요한 파일만 모은 임시 배포 패키지가 dotenv·네트워크·migration 실행 없이 import·health·인증 차단·migration metadata를 처리하는지 확인했다. 이 검사는 실제 Vercel 배포·PostgreSQL 연결을 대신하지 않는다.
- 2026-10-02에 별도 QA 계정 HTTP 19개, 모바일 390px 저장/승인/실패 화면, SQLite 백업·별도 빈 대상 복구, 추가 기준 6종 원본·격리를 확인했다. 이번에는 새 제공자 코드와 설정을 추가 검증했다.

## 실제로 사용하기 위한 다음 단계

Hugging Face 플러그인 계정 연결은 확인됐지만 도구의 OAuth 조회 권한은 앱의 추론 토큰과 다르다. 사용자 본인이 [HF 토큰 설정](https://huggingface.co/settings/tokens)에서 **Make calls to Inference Providers** 권한의 토큰을 발급해 **앱 설정 → AI 연결**에 입력·저장한다. 키를 채팅에 보내지 않는다. 연결 검사 후 실제 작성 흐름을 확인할 수 있다. [연결 절차와 현재 한도](docs/FREE_PROVIDER_SETUP.md).

HF 무료 기본 크레딧은 현재 월 **$0.10**이며 장기·무제한 운영을 보장하지 않는다. Groq Free 플랜은 요청·토큰 한도가 있는 대안이다. 제공자 계정의 실제 청구 설정을 확인해야 한다. OpenAI 공개 가중치 **gpt-oss** 사용과 상용 OpenAI API 무료 사용은 다르다. [HF 공식 요금](https://huggingface.co/docs/inference-providers/pricing), [Groq 공식 한도](https://console.groq.com/docs/rate-limits).

HF/Groq 생성 설정으로 웹 검색과 임베딩이 자동 활성화되지는 않는다. 현재는 확인한 공고·회사 자료 입력과 어휘 검색을 사용할 수 있다. 벡터 검색은 실제 PostgreSQL/pgvector 연결과 모델·차원 검증이 필요하다.

Supabase·Vercel 도구는 사용 가능하다. Supabase 조회 결과 개인 조직 1개, 프로젝트 0개이며 조직 선택 응답을 기다린다. Vercel 팀 조회 결과는 0개이고 배포된 프로젝트를 확인하지 못했다. 도구 설치와 DB/서비스 리소스 생성·배포는 구별한다.

공식 Vercel CLI **62.2.0**을 제외된 로컬 `work/deploy-cli`에 설치하고 버전·로그인·배포·링크 옵션을 확인했다. 설정·인증 파일은 제외된 `work/vercel-config`에 둔다. 후속 계정 조회에서 CLI는 logged out 상태이며 로그인은 완료되지 않았다. 실제 CLI 업로드 파일 검사(`--dry --json`)도 인증이 없어 완료하지 못했다. 배포·프로젝트 생성·요금 변경은 실행하지 않았다. [로그인 도움 도구](scripts/connect-vercel.ps1), [정확한 배포 경로와 첫 배포 대상](docs/VERCEL_FREE_BACKEND.md).

공개 실서비스에는 실제 Supabase DB/Auth·두 사용자 격리, backend HTTPS·Vercel 배포, 운영 DB/secret/백업 복구를 확인해야 한다. Jev 실연결은 선택 사항이다. 이 외부 검증을 완료했다고 기록하지 않는다. [배포 절차](docs/PRODUCTION_DEPLOYMENT.md), [요구별 기존 감사](docs/REQUIREMENT_COMPLETION_AUDIT.md).

무료 배포 후보는 개인·비상업 용도의 Vercel Hobby에 프런트엔드와 FastAPI를 별도 프로젝트로 올리는 경로다. 현재 공개 배포 자격증명과 Supabase 프로젝트를 준비하지 못해 실제 배포는 하지 않았다. [구체적인 무료 백엔드 절차](docs/VERCEL_FREE_BACKEND.md), [Vercel 공식 FastAPI 설명](https://vercel.com/docs/frameworks/backend/fastapi).

앱: http://127.0.0.1:3000/ . 실행과 종료는 [RUN_LOCAL](RUN_LOCAL.md)에 있다. 이번 실행 증거는 `work/free-service-local-audit.json`, 화면은 `work/ui-free-provider-settings.jpg`에 보관했다.


## 2026-10-03 upgrade checkpoint

필수 보완 4건과 업그레이드 6종을 구현했다. Python 339 통과/PG 3개 미실행, 프론트엔드 15개 검사 및 최신 lint/typecheck/build, 실제 UI/HTTP/파일/SQLite 복구를 확인했다. 현재 기록은 `docs/UPGRADE_PROGRESS.md`와 JSON의 `upgrade_progress`다. 실제 HF 작성·운영 PG/Auth·HTTPS·운영 복구/CI·Word 페이지 렌더는 남아 있어 전체 완료로 표시하지 않는다.


2026-10-03 추가 실DB/소스 감사: Python 353 통과와 별도 실제 PG 3 통과, PG16 migration 왕복·보호 적용·39개 테이블 복구/내용 일치 확인. 공개 회귀 사례 비식별 합성 교체와 미추적 소스 개인정보 검사 보강. 운영 계정 연결과 Word 페이지 검증은 미완료. 최신 상세 상태는 docs/UPGRADE_PROGRESS.md.
