# 무료 한국어 의미 검색

경험 정리에서 확인된 본인 자료를 색인하고, 검색 문장을 브라우저의 WASM 모델로 읽어 관련 자료를 찾는다. 설정한 HF/Groq 생성 API 키와 별개로 동작하며 임베딩 API 요금이나 추론 토큰을 사용하지 않는다. 처음 사용할 때 공개 모델·토크나이저·실행 파일을 다운로드한다. 문장은 기기에서 처리하고, 생성한 벡터는 인증된 본인 계정의 서버에 저장한다.

직무 근거 매핑은 기기에서 만든 검색 벡터와 모델 프로필을 요청에 전달한 경우에만 무료 의미 검색을 함께 사용한다. 벡터 없이 실행하는 서버 대화·자동 작업은 단어 검색을 유지한다. 서버가 브라우저 임베딩을 수행했다고 표시하지 않는다.

## 고정 모델과 실행

- 모델: `Xenova/multilingual-e5-small`
- 리비전: `761b726dd34fb83930e26aab4e9ac3899aa1fa78`
- 라이브러리: `@huggingface/transformers` 3.8.1
- q8 ONNX, 384차원, mean pooling, L2 정규화
- 검색은 `query: `, 자료는 `passage: ` 접두사 사용
- 512 토큰에서 잘라 처리하며 자료 본문은 최대 6,000자
- 가중치 118,308,185바이트, 토크나이저 약 17MB, WASM 약 22MB. 최초 전체 다운로드는 약 150MiB와 화면 코드이며 캐시 상태에 따라 다시 다운로드할 수 있다.

[ONNX 모델](https://huggingface.co/Xenova/multilingual-e5-small), [원 모델 설명](https://huggingface.co/intfloat/multilingual-e5-small), [Transformers.js](https://huggingface.co/docs/transformers.js/v3.8.1/index)를 기준으로 한국어 지원과 접두사·정규화 방식을 확인했다. 모델 다운로드가 무료라는 뜻이며 모든 기기의 실행 속도나 모든 검색 문장의 정확성을 보장하지 않는다.

## 저장 및 사실 경계

`local_evidence_embeddings`는 기존 OpenAI `evidence_embeddings`의 1,536차원 벡터와 분리된다. SQLite는 JSON 벡터와 실제 cosine 계산을 사용하고 PostgreSQL은 `vector(384)`와 pgvector cosine 거리 정렬을 사용한다.

검색 전에 자료 소유자·출처 소유자·확인 상태·FACT/EXPRESSION 구분·모델 프로필·현재 내용 해시를 확인한다. 제목·본문·판단 과정·수행 범위 등 근거 데이터, 출처 해시나 상태가 바뀌면 이전 벡터를 제외한다. 색인 생성 중 자료가 바뀌면 해당 항목 저장을 건너뛰고 새 자료 반영이 필요함을 반환한다. 표현 자료는 사실 자료 검색에 섞이지 않는다.

검색 점수는 관련 자료를 고르는 순서다. 사실 검증, 직접 수행 범위, 직무 적합성을 승인하는 증거로 사용하지 않는다. 기존 task metadata와 판단 재료 우선순위를 보존한다. 한 번에 32개 자료를 색인하고 페이지를 순회한다. 검색 대상이 5,000개를 넘으면 일부만 검색한 결과를 전체 결과처럼 반환하지 않고 범위를 나누도록 안내한다.

## 기능 확인

최신 Next.js 화면에서도 공개 모델 준비→본인 경험 2개 색인→한국어 검색을 실행했다. 관련 합성 보고서가 반환되고 미검증 업로드는 포함되지 않았다. 새 화면에서 저장된 색인을 다시 검색했으며 경고/오류를 관측하지 않았다 (`work/upgrade-browser-audit.json`, `work/ui-upgrade-semantic.png`). 실제 PG 및 개인자료 인수는 별도다.

합성 한국어 자료 3개에 고정 모델의 실제 임베딩을 생성하고 저장·검색했다. Node CPU와 실제 브라우저 WASM을 각각 확인했으며, 브라우저는 앞서 내려받은 같은 리비전의 공개 가중치를 로컬 테스트 서버로 재사용했다. 검색 요청과 가까운 합성 매출 분석 근거가 반환되고 다른 사용자의 자료는 반환되지 않았다. 이는 기능 확인이며 비교·성능 향상 실험이 아니다.

- 실제 모델 기록: `work/local-semantic-functional-audit.json`
- 실제 브라우저 기록: `work/local-semantic-browser-functional-audit.json`
- 브라우저 화면: `work/local-semantic-browser-pass.png`
- 회귀 검사: `tests/test_local_semantic.py`, `tests/test_retrieval.py`, `tests/test_task_retrieval.py`
- PostgreSQL 전용 검사: `tests/test_postgres_integration.py`의 다중 업무 키워드·한국어 부분 문자열·1,536/384차원 저장 분리·사용자 격리·오래된 내용 해시 검사는 `TEST_POSTGRES_URL`이 있어야 실행된다. 로컬 PostgreSQL 연결이 없으면 실행되지 않으므로 실제 PG 연결 검증 완료로 해석하지 않는다.

가중치와 합성 검증 파일은 무시되는 `work/`에만 저장했고 프로덕션 서버 패키지에 모델 가중치를 넣지 않았다.
