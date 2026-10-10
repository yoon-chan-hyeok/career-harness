# 반복 입력 캐시 개선

2026-10-04. 현재 외부 AI API 구조에 맞춘 입력 prefix 개선이다. 자체 GPU 서버의 KV 메모리·양자화·스케줄러를 설정한 것은 아니다.

## 요청 처리

역할별로 이미 선택한 자료만 사용한다. 확인된 공통 규칙·프로필·근거를 앞에, 바뀌는 문항·초안·수정 요청을 뒤에 두고 객체 키를 안정적으로 정렬한다. 순위가 있는 배열의 순서와 실제 자료 내용은 유지한다. 매 요청에서 새 결과를 생성하며 이전 응답을 재사용하지 않는다. 비용을 쓰는 prewarm, padding, 추가 모델 호출, 자동 모델 변경은 없다.

인증된 사용자 범위에서만 불투명 HMAC 구분값을 만든다. 입력의 `user_id`를 인증으로 사용하지 않는다. 익명 호출에는 요청마다 새 구분값을 넣는다. 사용자 권한은 기존 서버 검사가 결정하며 캐시 key는 별도의 보안·물리적 GPU 격리를 보장하지 않는다. 구분값·key·원문·서버 secret은 실행 로그에 저장하지 않는다.

역할, 실제 모델·제공자, 역할 지침·출력 schema, 자료 영역·참고 문서 버전은 OpenAI routing key의 범위를 나눈다. 최신 문서 내용은 항상 새 요청에 포함한다. 지원하는 입력은 JSON 값, Pydantic 모델, 날짜, UUID, Enum이다. 불안정한 집합·비정상 숫자·임의 객체는 원문을 노출하지 않고 거절한다.

## 제공자별 경계

| 제공자 | 앱이 보내는 항목 | 관측 |
|---|---|---|
| OpenAI Responses | 인증된 범위의 `prompt_cache_key`, 기존 `store=False` | 응답 usage의 실제 cached token만 기록 |
| Groq | 안정적인 messages, 기존 모델·출력 한도 | `prompt_tokens_details.cached_tokens`가 있을 때만 기록 |
| Hugging Face router | 안정적인 messages, 기존 모델·출력 한도 | 제공 경로가 수치를 보내지 않으면 미확인 |

HF/Groq에 지원이 검증되지 않은 cache key·retention·TTL 옵션을 보내지 않는다. OpenAI에서도 TTL·retention을 강제하지 않는다. `store=False`는 응답 보관 옵션이며 제공자 캐시를 끄는 설정이 아니다. 캐시 사용 여부·수명·가격은 실제 모델과 제공자가 결정한다. [OpenAI 공식 문서](https://developers.openai.com/api/docs/guides/prompt-caching), [Groq 공식 문서](https://console.groq.com/docs/prompt-caching), [HF 공식 프로토콜](https://huggingface.co/docs/inference-providers/en/tasks/chat-completion).

## 사용량과 비용

캐시 HIT, 실제 0인 MISS, 수치 없는 UNKNOWN, 잘못된 INVALID를 구분한다. 모의 응답은 프로토콜 검사 자료이며 실제 캐시 적중을 입증하지 않는다. 입력 재사용 비율은 관측된 동일 요청 집합의 `cached/input` 가중 비율이다. 미관측·잘못된 요청은 비율에서 제외하고 별도 횟수로 보여준다. 실패 응답도 실제 사용량이 있으면 포함하며 embedding은 생성 캐시 집계에서 제외한다. 일·월은 UTC 기준으로 현재 사용자만 집계한다.

캐시 정보가 없어도 실제 input/output token은 앱 한도에서 차감한다. cached token도 입력 한도에 포함한다. 필요한 비용 분해가 없으면 실제 추정 비용은 미확인으로 두고 실행 상한에는 보수적인 최대 예약을 유지한다. 설정 단가 계산은 제공자 청구서·무료 크레딧 잔액이 아니다.

## 설정과 되돌리기

- `CAREER_PROMPT_CACHE_ENABLED=1`: 기본값. `0`이면 이전 요청 배치로 돌아가며 앱 key를 보내지 않는다. 제공자 자체의 자동 캐시는 계속 가능하다.
- `CAREER_PROMPT_CACHE_SECRET`: 선택적 랜덤 서버 secret, 최소 32 UTF-8 byte. 여러 인스턴스에서 같은 값을 쓰면 사용자 구분값이 재시작 후에도 유지된다. 생략하면 프로세스별 임시 secret을 사용한다. 교체하면 기존 prefix와 routing key가 달라진다. 채팅·프런트엔드·소스에 넣지 않는다.

실제 HF/OpenAI/Groq 호출, 실제 KV 적중률, 속도·요금 절감은 계정 연결 후 확인해야 한다. 이번 범위에는 모델 비교·성능 개선 입증 실험과 유료 전환이 없다. 별도 GPU 서버는 추가하지 않는다.
