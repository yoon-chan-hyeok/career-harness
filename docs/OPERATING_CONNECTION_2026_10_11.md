# 실제 AI와 공개 회원가입 연결

2026-10-11 연결된 도구로 확인한 상태: HF `ych1390` Free 계정은 로그인돼 있으나 현재 OAuth 권한에는 추론 호출 권한이 없다. 현재 연결에서 Supabase 프로젝트 목록은 비어 있고, Vercel의 Career Harness 프로젝트 검색 결과와 팀 목록도 비어 있다. 다른 계정이나 현재 도구에 보이지 않는 범위의 프로젝트 존재 여부는 확인하지 않았다. 공개 소개 사이트는 합성 데모이며 운영 앱을 대신하지 않는다.

## 1. 실제 AI를 먼저 확인

HF의 현재 공식 요금표는 Free 계정에 기본 월 추론 크레딧을 제공하지 않는다. 기존 월 $0.10 안내는 현재 연결 판단에서 제외한다. 토큰 발급만으로 무료 호출이 가능해지지 않는다. 구매 없이 시작하려면 이미 구현된 Groq Free 경로를 사용한다. [HF 요금](https://huggingface.co/docs/inference-providers/pricing), [Groq 한도](https://console.groq.com/docs/rate-limits).

1. [Groq Console](https://console.groq.com/keys)에서 본인 계정의 Free 상태와 한도를 확인하고 앱 전용 API 키를 발급한다. 유료 Developer로 업그레이드하지 않는다.
2. 로컬 작업실의 **설정 → AI 연결**에서 Groq, `openai/gpt-oss-120b`, 발급한 키를 입력한다. 실제 무료 조건을 확인한 경우에만 확인 항목을 선택하고 저장한다.
3. **연결 검사**를 실행한 뒤 가상 근거로 자소서와 레쥬메 작성 흐름을 각각 확인한다. 연결 검사 한 번의 성공과 실제 문서 작성 성공을 구별한다.
4. 운영 배포에는 로컬 키 파일을 복사하지 않는다. 같은 제공자의 운영 키를 백엔드 프로젝트의 비밀 환경 설정에 직접 등록한다. 대화, GitHub, 브라우저 공개 변수에 키를 넣지 않는다.

백엔드 설정:

```dotenv
CAREER_LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-120b
# 실제 Free 조건을 확인한 뒤에만 1
GROQ_FREE_ONLY_CONFIRMED=1
JEV_SHADOW_ENABLED=0
```

`GROQ_API_KEY`는 별도 비밀 설정에 넣는다. 계정별 상한과 전체 공용 상한이 함께 적용되며, Groq 무료 한도는 이 앱의 모든 회원이 공유한다. 공식 표의 현재 gpt-oss-120b 기본값은 분당 30회·8,000토큰, 일 1,000회·200,000토큰이다. 실제 계정 한도가 우선한다. 무료 한도를 넘으면 생성 실패를 안내하고 직접 작성으로 이어가며 다른 유료 제공자로 자동 전환하지 않는다.

## 2. Supabase에 회원과 운영 자료 연결

1. [Supabase Dashboard](https://supabase.com/dashboard)에서 사용할 프로젝트를 지정한다. 무료 플랜 여부와 지역을 확인한다. 기존 개인 로컬 DB를 무조건 공개 DB에 옮기지 않는다.
2. 프로젝트 URL, publishable key, 백엔드 전용 secret key, DB 연결 주소와 공개 CA 인증서를 준비한다. URL과 publishable key는 로그인 화면용이고, secret key와 DB 비밀번호는 서버 전용이다.
3. 운영 DB에 기존 Alembic 마이그레이션을 적용하고 `deploy/supabase-security.sql`로 Data API 직접 접근 차단을 확인한다. 런타임은 transaction pooler, 배포 전 마이그레이션은 direct/session 연결을 사용한다. TLS 인증서 검증을 유지한다.
4. Supabase Auth에서 이메일 인증과 새 가입을 허용하고 익명 로그인을 끈다. 이메일 OTP 템플릿에는 `{{ .Token }}`을 포함한다. 운영 URL이 정해지면 Site URL도 맞춘다. [OTP 공식 안내](https://supabase.com/docs/guides/auth/auth-email-passwordless).

## 3. 가입 메일과 봇 차단 연결

Supabase 기본 발송기는 공개 회원가입용으로 사용할 수 없다. 기본 상태에서는 프로젝트 팀에 속하지 않은 주소에 발송하지 않으며 현재 시간당 2통 제한이 있다. 본인의 이메일 발송 서비스에서 발신주소/도메인을 인증하고 SMTP host·port·user·password를 Supabase Auth에 등록한다. 발신 도메인이 필요하면 본인이 보유한 도메인을 사용하며 구매를 자동으로 진행하지 않는다. [SMTP 공식 안내](https://supabase.com/docs/guides/auth/auth-smtp).

Cloudflare Turnstile에서 실제 프런트 도메인을 등록한다. secret key는 Supabase Auth의 CAPTCHA 설정에 넣고, 공개 site key는 앱의 `CAREER_CAPTCHA_SITE_KEY`에 넣는다. [CAPTCHA 공식 안내](https://supabase.com/docs/guides/auth/auth-captcha).

실제 본인 테스트 주소로 코드 수신·만료·재발송·CAPTCHA를 확인한 후에만 `CAREER_SMTP_CONFIGURED_CONFIRMED`, `CAREER_EMAIL_CONFIRMATION_CONFIRMED`, `CAREER_CAPTCHA_ENABLED_CONFIRMED`를 `1`로 설정한다. 이 값은 운영자 확인 기록이며 원격 설정을 자동 완료하는 스위치가 아니다.

## 4. Vercel에 실제 앱 배포

GitHub `yoon-chan-hyeok/career-harness`를 연결해 두 프로젝트로 배포한다. 백엔드 Root Directory는 저장소 루트, 프런트는 `frontend`다. 백엔드에는 DB/Auth/AI 비밀 설정을 넣고, 프런트 서버의 `BACKEND_URL`에는 배포된 백엔드 HTTPS 주소를 넣는다. Vercel 프로젝트의 실제 Production 대상과 접근 설정을 확인한다.

공개형 백엔드에는 `deploy/vercel-backend.env.example` 다음 `deploy/public-access.env.example` 설정을 적용한다. 핵심 값은 `AUTH_MODE=supabase`, `CAREER_ACCESS_MODE=public`, `CAREER_SHARED_SERVICE=1`이다. 실제 운영자 이름·문의 이메일·백업 보관 기간과 관리자 UUID도 지정한다. 처음에는 `CAREER_REGISTRATION_OPEN=0`으로 준비하고 테스트 후 `1`로 연다. Auth의 가입 허용 설정과 앱의 신규 회원 승인 설정은 별개다.

Vercel Hobby는 개인·비상업 용도로 제한된다. 개인 포트폴리오 운영 범위에서 시작하고 유료 판매 등 상업 운영을 계획하면 플랜 조건을 다시 검토한다. 무료 플랜은 상시 가동이나 무제한 트래픽을 보장하지 않는다. [Hobby 공식 안내](https://vercel.com/docs/plans/hobby).

## 5. 공개 전 실제 도메인에서 확인

- 테스트 계정 두 개로 이메일 가입 → 약관 동의 → 로그인 → 각 계정 자료 격리를 확인한다.
- 실제 AI 자소서/레쥬메 작성 → 검수 → 사용자 승인 → 저장 → 내보내기를 확인한다.
- 계정 중지·재인증 후 탈퇴, AI/메일 한도와 오류 안내를 확인한다.
- 운영 DB 백업과 복원, 삭제 요청 재적용, 용량·오류 알림을 확인한다.
- 확인을 마친 운영 URL로 소개 페이지의 시작 버튼을 연결한다.

계정 로그인·키 발급·이메일 발신 소유권 확인·운영자 정보는 본인의 실제 계정에서 준비해야 한다. 코드/DB 적용·배포·연결 검사·소개 링크 수정은 준비된 계정과 설정을 사용해 수행할 수 있다. 현재 이 안내 작성만으로 실제 AI나 공개 가입 운영이 연결된 것은 아니다. 작성 전략의 남은 규칙 구현과 전체 인수도 별도로 남아 있다.
