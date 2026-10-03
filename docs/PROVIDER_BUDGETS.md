# 단계별 모델·시간·토큰·비용 설정

`OPENAI_MODEL`은 명시적으로 정한 기본 모델이다. `OPENAI_SMALL_MODEL`을 추가하면 경험 구조화, 단순 문항 유형·역할 명칭·직접 답변·용어 과다·수정 라우팅, 표현 투영, 요약, 검색 결과 추출만 그 모델을 사용할 수 있다. 전략·집필·사실 검수·면접 검증은 기본 모델을 계속 사용한다. 특정 단계의 별도 모델은 운영자가 `OPENAI_STAGE_POLICIES`로 정하며, 제품이 임의로 최신 모델이나 더 저렴한 모델을 선택하지 않는다.

기본 시간 한도는 60초, 생성 토큰 상한은 16,384다. `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_OUTPUT_TOKENS`로 기본값을 바꾸거나 다음처럼 단계별로 설정한다. 모델명은 이용 가능한 실제 모델명으로 교체한다.

```json
{
  "truth_extraction": {"model": "explicit-small-model", "timeout_seconds": 30, "max_output_tokens": 4096},
  "writer": {"timeout_seconds": 60, "max_output_tokens": 16384, "max_input_tokens": 30000},
  "fact_reviewer": {"timeout_seconds": 60, "max_output_tokens": 8192, "max_cost_usd": 0.05}
}
```

API 요청의 timeout·max_output_tokens와 반환된 실제 latency·usage를 함께 확인한다. 생성 한도에는 보이지 않는 reasoning token도 포함된다. incomplete 응답은 완료 문서로 저장하지 않는다. 입력 토큰 상한과 비용 상한의 사후 검사는 응답을 문서 상태에 반영하기 전에 실행된다. 한도를 넘겼다고 이미 발생한 공급자 과금이 취소되지는 않는다. 계정 전체 과금 차단은 공급자 project의 예산/한도를 별도로 설정해야 한다.

비용 추정은 `OPENAI_PRICING_JSON`에 **해당 계정의 현재 모델 가격**을 명시했을 때만 한다. USD/million token 기준이며 캐시 읽기·쓰기와 tool call 가격을 분리한다. 아래는 필드 설명용 합성 수치이고 현재 요금표가 아니다.

```json
{
  "explicit-model": {
    "input_usd_per_million": 2,
    "cached_input_usd_per_million": 0.2,
    "cache_write_usd_per_million": 2.5,
    "output_usd_per_million": 8,
    "web_search_usd_per_call": 0.01
  }
}
```

실제 `input_tokens`, `output_tokens`, `cached_tokens`, `cache_write_tokens`와 관측된 검색 호출 수를 사용한다. 일반 입력은 전체 입력에서 캐시 읽기·쓰기를 뺀 값이다. 관련 요금이나 사용량·검색 호출 수를 모르면 cost는 `null`이다. Embedding은 실제 prompt_tokens를 입력 비용으로만 계산한다. 이 값은 마지막 응답의 추정치이며 공급자 invoice나 실패한 요청의 총 과금을 뜻하지 않는다.

명시적인 `max_cost_usd`를 설정했는데 계산에 필요한 가격이 없으면 API 호출 전에 거절한다. 사용량이 없거나 계산할 수 없는 응답도 비용 한도를 통과한 것으로 처리하지 않는다. 한도 초과 시 기존 근거·문서는 보존되고 실패 기록으로 남는다. 한도·모델·자료를 다시 확인한 뒤 사용자가 재시도할 수 있다.

확인한 계약: [OpenAI Responses 생성 상한](https://developers.openai.com/api/reference/python/resources/responses/methods/create), [OpenAI reasoning token 및 incomplete 응답](https://developers.openai.com/api/docs/guides/reasoning), [OpenAI 실제 캐시 사용량과 입력 비용 계산](https://developers.openai.com/api/docs/guides/prompt-caching).
