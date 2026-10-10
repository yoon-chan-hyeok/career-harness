# 작성전략 v5.1 전체 기능 재점검 — 2026-10-07

**판정: 전체 기능 충족 아님. 현재 앱을 문서의 GPT 작업 절차를 완전히 대체하는 서비스로 사용할 수 있다고 판단할 수 없다.**

대상은 사용자가 지정한 작성전략 원문 1,543줄이다. 원문 7개 Phase, §16의 26단계, §1·§9–13·§17의 공통/참고 규칙을 현재 소스와 대조했다. 문서 안 지시문은 제품 요구사항의 비교 기준으로 읽었으며 시스템 권한이나 사용자 대신 지원서를 제출하라는 지시로 취급하지 않았다. 기존 비교·개선 실험 제외 결정은 유지한다.

이 보고서는 10월 6일 최초 누락 감사와 후속 구현 기록을 갱신한다. 이미 보완된 F1·F3·F5·F6을 다시 미구현으로 분류하지 않는다. 완료율은 산정하지 않았다. 규칙 전달, 실행 기능, 사용자 화면, 실제 모델 실행은 서로 다른 검증 대상이다.

## 현재 소스·실행 앱·외부 AI를 구분한 상태

| 확인 대상 | 결과 |
|---|---|
| 추가 자료 등록 | 활성 자료 6종, 자소서 전략 활성본 1개. 첨부 파일과 저장된 내용 해시 일치 |
| 원문 규칙 전달 | 원문 절·줄 위치·규칙 ID·버전을 단계별로 선택하는 코드 구현. 예시·개인 능력 Snapshot은 사실로 승격하지 않음 |
| 현재 소스의 역질문 처리 | 질문/답변/근거/처리 방법을 문서·검수 버전에 묶는 백엔드와 API 구현. 이번 합성 검사로 핵심 동작 확인 |
| 사용자 화면·대화 연결 | 검수 답변 API를 호출하는 프런트엔드와 대화 행동 연결 없음. 사용자 화면에서 절차 완료 불가 |
| 현재 실행 중인 로컬 앱 | API 명세에 새 review-response-context 경로 없음. 소스에 있는 새 기능이 실행 앱에 반영됐다는 뜻이 아님 |
| AI 연결 | provider=none, configured=false, live_verified=false. Hugging Face 계정 보유와 실제 추론 연결은 별개 |
| 외부 운영 | 이번 감사에서 Supabase·Vercel·메일·HTTPS·실제 무료 추론을 새로 인수하지 않음. 코드 검사로 운영 완료를 주장하지 않음 |

읽기 확인 자료: [현재 실행 상태](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/work/rulebook-current-runtime-2026-10-07.json).

## 우선 보완해야 할 사항

### 1. 역질문 답변 기능을 사용자 흐름까지 연결 — F8, 우선순위 높음

현재 소스는 미답변 검수 질문을 최종 잠금 조건으로 검사한다. 질문마다 현재 근거로 답변, 문서 수정, 근거 보완, 면접 준비, 공백 인정의 처리 방법을 저장할 수 있다. 직접 확인 선택이 필요하고 정확한 원문 인용을 검사한다. 사실 문제를 면접 대비로 넘기거나 “보완하겠다”는 계획만으로 완료 처리하지 않는다. 새 검수는 이전 답변을 재검토 대상으로 만든다.

그러나 이 API를 부르는 화면/대화 기능이 없다. 이 소스만 앱에 반영하면 질문이 발생한 사용자가 최종 잠금 앞에서 멈출 수 있다. 또한 저장된 답변은 제출 묶음에 보존될 수 있지만 면접 자료 생성기가 그 답변을 읽어 연결하지 않는다. 이력서의 역질문/답변 검증에서도 Resume 규칙 대신 Cover 규칙 묶음을 선택하는 경로가 확인됐다.

완료 기준: 답변 화면·대화·오른쪽 보관함, 보완 후 재검수, 버전별 결과, 이력서 규칙 선택, 제출본 기반 면접 자료까지 연결하고 브라우저에서 완료를 확인한다. 답이 약한 경우 전략/문항 수정은 기존 사용자 승인 절차를 유지한다.

근거: [답변 처리](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/review_resolution.py:96), [잠금 조건](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/workflow.py:1054), [대화 행동 목록](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/conversation.py:73), [규칙 묶음 선택](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/references.py:229), [면접 자료 생성](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/interview_defense.py:78).

### 2. 회사 조사와 Why Now를 기본 작성 흐름에 연결 — F2

새 지원에서 “ㄱㄱ”는 회사 조사를 건너뛰고 직무 분석으로 진행한다. 회사 근거와 채용 배경이 비어도 진행 가능하다. 실시간 조사 코드는 OpenAI 경로에 묶여 있고 Hugging Face 선택은 출처 없는 수동 대체 상태가 된다.

수동 JD-only 지원 자체는 기존 명세의 요구이므로 없애면 안 된다. 다만 조사 완료와 제한된 자료로 진행 중인 상태를 명시적으로 구별해야 한다. 최신 JD·회사 사업·조직·과거/유사 JD와 출처에 따른 Why Now 가설을 확인하는 기본 순서가 필요하다.

완료 기준: 무료 추론 제공자와 별개로 사용 가능한 자료 수집 경로, 수동 자료 입력과 정보 부족 표시, 출처 있는 가설 확인, 기본 “다음” 순서 검증.

근거: [조사와 직무 분석](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/workflow.py:170), [기본 진행](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/workflow.py:1666).

### 3. 승인된 개인 표현 저장·재사용 — F7

과거 지원서를 표현 자료로 검색하고 사실과 분리하는 기능은 있다. 하지만 사용자가 좋아하거나 직접 다듬은 문구는 실제 작성 입력에서 재사용되지 않는다. 표현 변환 결과의 preferred_patterns는 항상 비어 있고, 최종 잠금만으로 재사용 표현 자료가 생기지도 않는다.

완료 기준: 사용자가 승인한 문구/논리 구조를 별도 저장하고, 이름·날짜·수치·기여 등 오래된 사실을 제거하거나 현재 사실로 확인한 뒤 다음 문항 설계에서 조회한다. 자동 사실 승격이나 과거 지원서 전체 복사는 금지한다.

근거: [표현 변환](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/retrieval.py:306), [최종 잠금](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/workflow.py:1054).

### 4. Role Noun과 제출 전 마지막 세 질문을 명시적으로 확인

“이 사람은 무슨 사람인가?” 판정은 현재 채용담당자 지침과 선택적인 Jev 분기에 있다. 기본 경로의 독립된 최종 결과·통과 조건은 아니다. §17의 맡길 업무, 본업을 실제로 원하는지, 경험이 그 일을 증명하는지의 세 답변 확인 없이도 READY_TO_FREEZE가 된다.

완료 기준: 현재 전략·문서·근거에 묶인 세 질문의 구체적인 답과 확인 상태, 본업과 첫 직업 명칭의 일치 확인, 부족할 때 돌아갈 단계를 기록한다. 지원자의 의향을 AI가 대신 지어내면 안 된다.

근거: [선택적 역할 명칭 검사](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/workflow.py:851), [제출 준비 판단](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/workflow.py:1195).

### 5. 문항 간 반복과 프로젝트별 표현 경계의 적용 검증

동일 메시지는 차단하지만 비슷한 메시지와 반복 백분율은 경고 수준이다. 10건 같은 일반 수치 반복은 결정적 검사에서 발견되지 않는다. AI 문서 간 검토가 보완할 수 있으나 실제 호출로 확인하지 않았다.

§10의 프로젝트별 캐릭터·금지 표현은 규칙 컴파일에서 제외되어 있다. 실제 근거에 수행 범위·금지 주장이 등록되면 검사는 가능하지만 첨부 문서를 등록했다는 이유만으로 Face의 전체 개발/배포 과장이나 OCR의 미측정 비용 절감 같은 경계가 프로젝트별로 자동 보장되는 것은 아니다. 예시를 사실로 복사하지 않는 보호는 유지하면서, 현재 근거와 맞는 표현 제약을 연결해야 한다.

근거: [문서 간 검사](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/document_qa.py:24), [원문 절 선택 범위](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/backend/career/rulebook.py:15).

## 원문 26단계 대응표

“구조 구현”은 데이터·실행 경로 또는 차단 조건을 확인했다는 뜻이다. 실제 AI 문장 품질, 의미 판단의 정확성이나 모든 사용 사례 완료까지 의미하지 않는다.

| 번호 | 원문 요구 | 현재 판정 | 확인 내용·남은 점 |
|---|---|---|---|
| 1 | 최신 JD | 부분 | 원문 저장·마감/상태/출처 구조 있음. 최신 원문 자동 확인과 전체 필드 점검은 미완 |
| 2 | 회사·사업·조직 조사 | 부분 | 조사/수동 입력 구조 있음. 기본 흐름에서 생략 가능, 무료 모델 조사 미연결 |
| 3 | 과거·경력·현직자·유사 JD | 부분 | 과거 자료·날짜·현재 요건 구분 가능. 실제 수집을 완료시키는 기본 흐름은 없음 |
| 4 | Why Now | 부분 | 채용 배경·출처 기반 추론 구조 있음. 가설 확인 없이 진행 가능 |
| 5 | Actual Output 3개 | 부분 | 산출물 구조 있음. 1개만 있어도 유효하고 “3개” 기준의 결과 점검 없음 |
| 6 | Base Profession / Specialty / Tool | 구조 구현 | 독립 필드와 직무 전용 분석 있음. 하이브리드/순수 기술직 의미 판단은 실제 AI 검증 필요 |
| 7 | Main Skill / Differentiator | 구조 구현 | 구분·우선순위·근거 매핑 있음. 출력 적용 품질 확인 필요 |
| 8 | Direct / Adjacent / No Evidence | 구조 구현 | 유형·근거 ID·업무 산출물 검사, 미지원 산출물 기록 |
| 9 | Fatal Gap | 구조 구현 | 전략의 Gap·위험·보완 방향, 핵심 Gap 적합도 제한 |
| 10 | Fact 재확인 | 구조 구현 | 현재 정정·원자료·기여·금지 주장, 매핑 전 교정/회고 입력 |
| 11 | 맡길 일 한 문장 | 구조 구현 | assignment_statement 필드. JD·근거와 의미상 일치하는지 실제 검증 필요 |
| 12 | Persona | 구조·승인 구현 | 직무·근거 분석 후 전략 제안/사용자 승인 |
| 13 | 문항 역할 배분 | 구조·차단 구현 | 다문항에서 현재 역할 배분 승인 필수. 직접 API 우회와 새 문항 추가 검증 |
| 14 | 문항 의도 | 구조 구현 | 유형·평가 의도 저장. 모든 문항 유형의 세부 내용 품질은 미검증 |
| 15 | 문항 전 Fact 재확인 | 구조 구현 | 설계에 원문·지표·확인된 판단/기여/금지 주장 전달 |
| 16 | 과거 자소서 검색 | 부분 | 표현 검색·안전한 스타일 전달. 선호/잠금 문구 재사용 미완 |
| 17 | Operational Value 번역 | 부분 | 업무 가치/기술 결과/측정한 성과 구분과 성과 근거 조건. 번역 내용이 비어도 허용 |
| 18 | Provisional Claim | 구조 구현 | 핵심/보조 주장 후보와 승인 전 상태 |
| 19 | Evidence Test → Claim Lock | 구조·차단 구현 | 인용·네 가지 검사·별도 결과 필수. 현재 테스트 통과 전 승인/작성/준비 차단 |
| 20 | PODAEIJ | 지침 및 일부 구조 | 판단·통찰·직무 연결과 원문 구조 제공. 문항에 필요한 요소 선택 결과를 전용으로 검사하지 않음 |
| 21 | 초안 | 구조·차단 구현 | 전략·메시지 승인 후 생성, 선택 사실·현재 프로필·회사 출처·분량 전달 |
| 22 | Fact / Ownership | 구조·차단 구현 | 주장 장부·수치·수행 범위·출처 검사와 사실 검수, 변경 시 재검토 |
| 23 | Reverse Test | 백엔드 일부 구현 | JD·본업·전략 입력과 답변 버전/차단 확인. 화면·대화·재설계/면접 연결 미완 |
| 24 | Red Team | 백엔드 일부 구현 | 독립 채용담당자 검수와 처리 방법 구조. 사용자 대응 절차 전체 미완 |
| 25 | 압축 | 부분 | 글자 수·보호 문장·수정 제안/승인 있음. 원문의 삭제/보존 우선순위는 주로 지침 |
| 26 | Lock | 부분 | 문서·검수·Claim·Fact 보관 및 제출과 분리. 표현 재사용·면접 답변 연결·최종 질문 미완 |

## 세부 규칙의 판정

| 원문 | 현재 적용 범위 |
|---|---|
| §1 핵심 원칙 | 사실 우선, Persona 후행, 키워드와 직무 적합 구분, 본업과 차별점 분리 지침·구조 있음 |
| §4-0 과거 실패·교정 | 최신 교정과 범위가 맞는 과거 회고를 매핑/전략/문항에 전달. 결과를 원인·규칙으로 자동 승격하지 않음 |
| §4-4 사실 우선순위 | 현재 명시적 정정·검증된 근거를 우선. 정정 시 파생 문서 무효화, 이미 보관한 제출본 보존 |
| §5-4 소재 반복 | 같은 경험의 재사용 가능. 같은 Fact·숫자·결론·메시지 반복의 모든 형태를 확실히 잡는 상태는 아님 |
| §6-6 여러 경험, 하나의 메시지 | 선택한 대표 경험 유지와 보조 경험 연결 허용. 모든 주장과 현재 근거를 테스트 |
| §7-1·§13 글쓰기 순서 | 첫 2–3문장 답변, 기술보다 판단, 의미 뒤 숫자 등 원문 지침 전달. 모든 문장에 대한 적용 실증 없음 |
| §7-2 Build 우선과 평가 직무 예외 | 원문 지침 전달. 실제 수행 근거가 있는 Build만 사용해야 함 |
| §7-2 운영 가능성과 사업 성과 | 측정한 운영 지표 없는 Business Impact 격상 차단. 인과·의미 판정은 모델/사람 검수 필요 |
| §7-3~4 지원동기·현장 학습 | 원문과 역질문 지침 있음. 실제 본업 의향 답변을 사용자 절차 끝까지 연결해야 함 |
| §7-5 문항별 구조 | 지원동기·직무·가치관·협업·도전·강약점·포부 절을 전달. 각 유형의 완성 결과와 실제 AI 검증 필요 |
| §8-4 Role Noun | 기본 최종 판정으로 필수 연결되지 않음 |
| §9 Fact / Expression / Example | 사실과 표현 분리. Example은 별도 DB가 아니라 표현 자료 계열로 처리하며 물리적으로 DB 3개일 필요는 없음 |
| §10 프로젝트별 캐릭터 | 현재 근거의 경계는 검사 가능. 원문의 프로젝트별 규칙 자동 적용은 미완 |
| §11~12 Persona 원형·능력 Snapshot | 과거 스냅샷을 영구 사실로 등록하지 않는 것은 적절. 최신 사실/근거를 계속 우선 |
| §13 Ownership·AI 보조·숫자 | 직접/기존 코드 수정/AI 보조/팀/연구실 구조와 지표 범위 검증 있음. 과장 의미의 완전 판정은 미검증 |
| §14 하이브리드 직무 전체 예시 | 구성 요소는 상당 부분 존재하나 조사부터 약한 동기 답변의 재설계까지 전 과정 인수 증거 없음 |
| §15~16 기존 순서 호환 | 승인·사실·문서 보존 구조는 유지. 조사/표현/검수 대응의 연결이 남음 |
| §17 제출 전 세 질문 | 별도의 구체적 답변/확인 결과 없이 제출 준비 상태로 진행 가능 |

## 이번 검증과 수정 범위

전체 Python 회귀는 **550 passed, 6 skipped**로 완료됐다. 제외된 6개는 별도 PostgreSQL 환경 검사이며 이번에 운영 DB 검증까지 완료했다는 뜻이 아니다. Ruff 통과, 지정된 프로젝트 Python 환경의 Pyright 0 errors / 0 warnings, 프런트엔드 타입 검사·lint 및 기능 검사 25개가 통과했다. 이번 감사에서 production build와 실제 브라우저 종단 검사는 새로 수행하지 않았다.

전체 회귀와 별도로 현재 기능/누락 진단 20개를 합성 메모리 DB에서 실행했다. **11개는 구현 동작 확인, 9개는 누락을 재현하는 진단**이다. 후자의 “통과”는 구현 완료를 뜻하지 않는다.

진단으로 확인한 구현: 역질문에 직무 문맥 제공, 채용담당자의 비공개 근거 접근 차단, 미답변 잠금 차단, 수동 검수로 기존 질문 삭제 불가, 자소서/레쥬메 답변 잠금, 원문 인용/수동 확인, 사실 문제의 면접 대비 우회 차단, 보완 계획만으로 완료 불가, 검수 변경 시 답변 무효화, AI 부정 판정 차단, 다른 소유자 접근 차단.

진단으로 확인한 누락: 기본 조사 생략, HF 조사 빈 출처, 표현 재사용, 일반 수치 반복, Resume 검수 규칙 선택 2건, 마지막 세 질문, 면접 자료의 저장 답변 연결, 화면/대화 답변 연결.

전체 검사 첫 실행에서 인증 테스트 1개가 실패했다. 미래 발급 시각을 테스트 수집 시점에 계산해 두었고, 전체 실행이 60초 이상 걸리면서 검증 시점에는 미래가 아니게 된 테스트 시간 의존 문제였다. **각 테스트 실행 시점에 시각을 계산하도록 테스트만 수정했다. 인증 검증 기준이나 제품 코드는 완화하지 않았다.** 이번 감사에서 새 제품 기능을 구현하거나 일반 앱을 재시작하지 않았다. 기존 진행 중인 변경도 보존했다.

- [현재 상태 진단 20개](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/work/rulebook-current-probes-2026-10-07.xml)
- [진단 코드: 구현 확인과 누락 확인을 이름으로 구별](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/work/test_rulebook_current_audit.py)
- [전체 회귀 최초 실행](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/work/rulebook-current-audit-2026-10-07.xml)
- [수정 후 전체 회귀](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/work/rulebook-current-audit-2026-10-07-final.xml)
- [테스트 시간 계산 수정](C:/Users/ych13/Documents/Codex/2026-09-29/codex-master-prompt-md/outputs/career_harness_codex_one_shot_v2_2_FINAL/tests/test_production_security.py:102)

## 이어서 구현할 순서와 완료 조건

1. 진행 중인 역질문 처리 기능의 화면·대화·보관함·이력서 규칙·면접 자료 연결을 완성한다.
2. 무료 모델과 함께 사용할 조사 경로와 명시적 JD-only 상태, Why Now 확인을 연결한다.
3. 승인된 표현의 저장·안전한 재사용과 프로젝트별 표현 경계를 연결한다.
4. Role Noun, 반복 내용 검사, 마지막 세 가지 답변을 현재 문서 버전의 제출 판단에 연결한다.
5. 작성전략뿐 아니라 기존 구현 팩과 나머지 5종 문서까지 전체 요구사항 표를 완성하고, 하이브리드/순수 기술직·자소서/레쥬메·수정/재검수의 종단 흐름을 확인한다.
6. 실제 무료 추론과 운영 환경으로 인수한다. 이 단계 전까지 “GPT 절차 완전 대체”나 “실서비스 완료”로 보고하지 않는다.

현재 전체 구현 목표는 진행 중이다. 이번 확인 요청에 대한 결론은 **중요한 기반과 승인·검수 장치는 구현됐지만, 문서의 모든 기능을 사용자 앱에서 끝까지 수행하는 상태는 아직 아니다**이다.
