# 무료 AI 제공자 연결

이 안내는 사용자가 이미 가진 Hugging Face 계정으로 실제 생성 API를 연결하는 절차다. Hugging Face 토큰을 발급받았다는 사실과 무료 추론 잔액이 있다는 사실은 다르다. 계정 청구 설정은 이 앱이 원격으로 검증하지 않는다. 현재 연결 성공과 한국어 작성 품질은 실제 진단·작성 결과로 확인해야 한다.

2026-10-03 Hugging Face 연결 도구에서 계정 로그인과 Free 계정 상태를 확인했다. 현재 연결의 OAuth 권한에는 Inference Providers 호출 권한이 없으며, 앱에 저장할 수 있는 토큰도 제공하지 않는다. 도구 연결과 이 서비스의 생성 API 연결은 별도다. 아래 절차로 본인 전용 추론 토큰을 만들어 앱의 **AI 연결**에 직접 입력해야 한다.

## 제공자 선택

| `CAREER_LLM_PROVIDER` | 모델 설정 | 서버 비밀 설정 | 무료 사용의 조건 |
|---|---|---|---|
| `huggingface` | `HF_MODEL=openai/gpt-oss-120b:fireworks-ai` | `HF_TOKEN` | HF 무료 크레딧 잔액, 청구·custom key 설정 확인, `HF_FREE_ONLY_CONFIRMED=1` |
| `groq` | `GROQ_MODEL=openai/gpt-oss-120b` | `GROQ_API_KEY` | 실제 계정 Free tier, 현재 요청·토큰 한도, `GROQ_FREE_ONLY_CONFIRMED=1` |
| `openai` | 명시적인 `OPENAI_MODEL` | `OPENAI_API_KEY` | 무료 상용 API라고 가정하지 않는다. 계정의 실제 요금·이용 권한 필요 |
| `none` | 없음 | 없음 | 외부 생성 호출 없이 직접 작성·승인·검수 |

환경 선택 값을 비우면 개인 로컬 환경에서는 저장한 연결 설정을 먼저 사용하고, 그 설정도 없으면 기존 `OPENAI_API_KEY`/`OPENAI_MODEL` 설정과의 호환 경로를 사용한다. 유료 OpenAI 자동 선택을 원하지 않으면 `none` 또는 선택한 무료 제공자를 명시한다. 두 무료 확인 값은 기본 `0`이다. `1`은 사용자가 해당 계정 설정을 확인했다는 기록이며, 제공자의 과금을 막는 API 옵션이나 영구 무료 보증이 아니다.

개인 로컬 환경에서는 **설정 → AI 연결**에서 HF/Groq, 모델, 본인 토큰과 무료 확인을 저장하고 **연결 검사**를 눌러 확인할 수 있다. 로컬 소유자만 변경할 수 있으며 키는 Git 제외 `.provider-settings.json`에 보관한다. 이 화면을 사용하려면 `CAREER_LLM_PROVIDER`와 선택한 제공자의 키·모델·무료 확인 환경변수를 설정하지 않는다. `.env.example`을 복사했다면 해당 제공자의 `HF_*` 또는 `GROQ_*` 줄을 주석 처리한다. 서버 환경 설정은 로컬 저장값보다 우선하며, 운영에서는 로컬 키 파일을 사용하지 않는다.

gpt-oss는 Apache 2.0으로 공개된 OpenAI 가중치 모델이다. Hugging Face/Groq에서 이 모델을 사용하는 것은 비공개 GPT 모델의 OpenAI API를 무료로 사용하는 것이 아니다. [OpenAI 공식 모델 설명](https://developers.openai.com/api/docs/models/gpt-oss-120b).

## 1. 기존 Hugging Face 계정 확인

1. 본인 계정의 [Inference Providers 설정](https://huggingface.co/settings/inference-providers)과 [청구 설정](https://huggingface.co/settings/billing)을 확인한다. 무료 개인 계정의 공식 기본 크레딧은 월 $0.10이며 변경될 수 있다. 이 작은 한도만으로 무제한 실서비스를 운영할 수 있다고 판단하지 않는다.
2. 무료 범위만 사용하려면 추가 크레딧 구매·자동 충전·custom provider key를 사용하지 않는다. custom key가 등록된 제공자는 HF 무료 크레딧 대신 외부 제공자에게 직접 청구될 수 있다. 유료 잔액이 있거나 청구 상태를 모르면 확인 값을 `0`으로 유지한다.
3. [토큰 설정](https://huggingface.co/settings/tokens)에서 이 앱 전용 fine-grained 토큰을 만들고 **Make calls to Inference Providers** 권한만 부여한다. 불필요한 저장소 쓰기 권한은 부여하지 않는다. 토큰은 대화나 공개 저장소에 보내지 않는다.
4. 개인 로컬에서는 앱의 **설정 → AI 연결**에 입력한다. 서버 환경으로 관리할 때는 프로젝트 루트의 Git 제외 `.env` 또는 백엔드 호스트의 secret manager에 저장한다. 프런트엔드, `NEXT_PUBLIC_*`, Vercel 화면 프로젝트에는 넣지 않는다.

HF는 요청을 공식 라우터로 보내면 제공자별 별도 계정 없이 라우팅하고 HF 계정 크레딧을 사용한다. 현재 코드 경로는 `https://router.huggingface.co/v1/chat/completions`의 JSON Schema 출력이다. 모델의 `:fireworks-ai` suffix를 유지해 문서에서 확인한 제공자를 고정한다. 가용성·요금·모델 이름은 배포 시 다시 확인한다. [HF 인증과 제공자 선택](https://huggingface.co/docs/inference-providers/index), [HF 청구](https://huggingface.co/docs/inference-providers/pricing), [gpt-oss 구조화 출력 예제](https://huggingface.co/docs/inference-providers/guides/gpt-oss).

키를 제외한 설정 예시:

```dotenv
CAREER_LLM_PROVIDER=huggingface
HF_MODEL=openai/gpt-oss-120b:fireworks-ai
HF_FREE_ONLY_CONFIRMED=1
CAREER_LLM_TIMEOUT_SECONDS=60
CAREER_LLM_MAX_OUTPUT_TOKENS=4096
CAREER_LLM_STAGE_POLICIES={}
CAREER_LLM_PRICING_JSON={}
JEV_SHADOW_ENABLED=0
```

`HF_TOKEN`은 비밀 설정에 별도로 넣는다. 예제의 확인 값 `1`은 위 청구 확인을 완료했을 때만 사용한다. 여러 작성·검토 호출과 추론 출력이 무료 잔액을 소모할 수 있다. 작은 합성 입력으로 먼저 연결을 확인한다.

## 2. Groq Free tier를 선택하는 경우

HF 잔액 소진 때문에 제공자를 바꾸려면 직접 선택 설정을 변경한다. 앱이 다른 키나 유료 제공자로 자동 전환하지 않는다. Groq Console의 실제 계정이 Free tier인지 확인하고 Developer tier로 업그레이드하지 않는다. 현재 공식 무료 한도 표의 gpt-oss-120b/20b는 30 RPM, 1,000 RPD, 8,000 TPM, 200,000 TPD지만 계정 예외·변경이 있으므로 Console의 본인 한도를 기준으로 한다. 초과 호출은 429로 실패할 수 있다. [Groq 한도](https://console.groq.com/docs/rate-limits), [청구와 유료 업그레이드](https://console.groq.com/docs/billing-faqs).

```dotenv
CAREER_LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-120b
GROQ_FREE_ONLY_CONFIRMED=1
CAREER_LLM_TIMEOUT_SECONDS=60
CAREER_LLM_MAX_OUTPUT_TOKENS=4096
JEV_SHADOW_ENABLED=0
```

본인의 `GROQ_API_KEY`를 백엔드 비밀 설정에 넣는다. 요청은 `https://api.groq.com/openai/v1/chat/completions`로 보낸다. Groq는 gpt-oss-120b/20b의 strict JSON Schema 출력을 지원하지만, strict 모드는 모든 필드를 필수로 지정하고 모든 객체의 추가 필드를 막아야 한다. 현재 Career Harness의 레쥬메 등에는 선택 필드와 동적인 매핑이 있어 Groq 어댑터는 `strict=false`를 사용한다. 형식 일치를 서버에서 보장받는 방식은 아니며, 모든 결과를 로컬 Pydantic 스키마로 검증하고 통과하지 못한 결과는 저장하지 않는다. 사실·출처·수치·본인 역할 검수도 별도로 유지한다. [Groq 구조화 출력](https://console.groq.com/docs/structured-outputs).

## 3. 설정과 실제 호출을 구분해 확인

프로젝트의 Python 환경에서 실행한다. PowerShell에서는 이 작업공간의 Python 경로 또는 설치한 가상환경을 사용한다.

```powershell
# 기본 실행: 설정 검사. 외부 생성 호출 없음.
python scripts/deployment_preflight.py
# 선택한 제공자에 합성 입력으로 실제 1회 구조화 호출.
python scripts/deployment_preflight.py --live-ai
```

`--live-ai`는 현재 설정에서 선택된 생성 제공자에 1회 요청한다. 화면에 저장한 로컬 설정과 환경 설정의 우선순위를 위 절차대로 확인한 뒤 실행한다. 무료 제공자를 선택했다면 무료 할당량을 소비하며, 계정이 유료라면 요금이 발생할 수 있다. 출력은 검사 상태와 오류 종류이며 키·입력 자료·모델 응답 원문을 출력하지 않는다. `selected_ai.live_verified=true`는 짧은 합성 요청의 스키마가 처리됐다는 뜻이고, `status=ok`여야 기대한 `ok=true` 응답까지 확인한 것이다. 개인 지원서 작성 품질, 전체 흐름, 임베딩, 웹 조사 또는 Jev가 검증됐다는 뜻이 아니다. CLI 결과는 화면의 연결 검사 성공 기록을 갱신하지 않으므로 화면의 상태를 갱신하려면 **연결 검사**를 실행한다.

기존 `--live-openai`는 선택 제공자와 관계없이 OpenAI를 직접 호출하는 유료 가능 진단이다. 무료 제공자를 확인할 때는 `--live-ai`를 사용한다. `--live-jev`도 독립적인 외부 호출이다. 기본 검사에 이 옵션들을 자동 추가하지 않는다.

## 4. 한도·실패 후 계속 작업

401/403은 키·권한 설정, 402는 잔액, 429는 요청·토큰 한도를 확인한다. 실패한 생성 결과는 승인된 문서로 저장하지 않고 기존 자료와 승인 상태를 유지한다. 무한 재시도, 임의 모델 교체, 다른 계정 토큰 수집, 비공식 프록시 우회는 사용하지 않는다.

연결이 회복될 때까지 직접 작성·편집·승인으로 진행할 수 있다. 필요한 경우 `CAREER_LLM_PROVIDER=none`으로 바꾸고 서버를 다시 시작한다. 운영에서 `CAREER_REQUIRE_AI=1`이면 생성 제공자 미설정 상태를 허용하지 않으므로 계획한 수동 운영에 한해서 `0`을 명시한다. 무료 확인 값이나 출력 토큰 제한만으로 계정의 유료 청구를 방지했다고 주장하지 않는다.

제공자 공통 설정은 `CAREER_LLM_TIMEOUT_SECONDS`, `CAREER_LLM_MAX_OUTPUT_TOKENS`, `CAREER_LLM_SMALL_MODEL`, `CAREER_LLM_STAGE_POLICIES`, `CAREER_LLM_PRICING_JSON`이다. 생략한 값은 기존 `OPENAI_*` 설정과 호환된다. 작은 모델은 명시적으로 설정한 경우에만 제한된 단계에 사용한다. 현재 실제 모델 요금을 모르면 `CAREER_LLM_PRICING_JSON={}`를 유지하며 비용은 `null`로 기록한다. 무료 할당량 사용과 모델의 명목상 비용 추정은 별개다.

HF/Groq 생성 연결만으로 OpenAI 전용 웹 조사나 임베딩이 활성화되지 않는다. 조사에는 수동으로 확인한 출처를 사용할 수 있다. 현재 PostgreSQL 벡터 색인은 1,536차원을 사용하며 로컬 공개 임베딩 모델로 바꾸려면 차원·모델 버전 관리와 재색인이 별도로 필요하다. SQLite의 현재 키워드 검색을 실제 벡터 검색이라고 표시하지 않는다.

## 5. Jev와 출시 조건

공식 Jev는 TypeSafe의 `https://api.typesafe.ai/v1/systemone`이며 키가 필요하다. 현재 확인한 공식 문서는 이 계정의 무료 API 잔액을 보장하지 않는다. `JEV_SHADOW_ENABLED=0`을 유지하고, 실제 계정의 무료 잔액과 키가 확인된 경우에만 선택적으로 연결한다. Jev 이름을 사용한 독립 웹사이트·공개 모델을 원 제작사의 Jev로 표시하지 않는다. [TypeSafe 시작 안내](https://docs.typesafe.ai/introduction/quickstart), [공식 API](https://docs.typesafe.ai/api).

이 프로젝트는 사용자의 [출시 결정](USER_DECISIONS.md)에 따라 비교 실험을 출시 필수 조건으로 삼지 않는다. 제공자 간 품질·속도·비용 개선을 입증했다는 주장도 하지 않는다. 실제 로그인·사용자 격리·작성/검수/승인·실패 복구·백업 복원·HTTPS·비밀정보 제외 검증은 계속 필요하다. 실제 외부 연결 전에는 출시 완료 또는 실모델 검증 완료로 표시하지 않는다.

HF CPU Basic은 시간당 비용이 없지만 현재 공식 문서는 Docker/Gradio compute Space 생성에 유료 구독이 필요하다고 설명한다. 무료 개인 계정의 최대 2개 ZeroGPU Gradio Space 예외는 이 FastAPI 컨테이너의 상시 호스팅과 다르다. 무료 하드웨어의 절전과 비영구 디스크 제약도 있다. 이 앱의 무료 운영과 HF의 영구 무료 FastAPI 호스팅을 동일시하지 않는다. [Spaces 현재 조건](https://huggingface.co/docs/hub/spaces-overview).
