# 기존 v4.1 증분의 통합 I01 인수

원래 구현은 `codex/v41-guide-retrieval` / `26d89a9` / [PR #2](https://github.com/yoon-chan-hyeok/career-harness/pull/2)에 보존한다. 당시 v3 위에 쌓였던 PR 순서는 2026-10-22 사용자가 지정한 통합 handoff로 대체됐다. 현재 순서는 [I00 PR #3](https://github.com/yoon-chan-hyeok/career-harness/pull/3) → I01 가이드 → I02 Context/Experience다.

이 브랜치는 네 Python 모듈·기존 가이드 검사만 재사용한다. v3 API·계약·Shadow 코드는 함께 가져오지 않았다. C/v4와 v4.1은 하나의 Career Harness의 상위·하위 명세다.

- 상세 현재 계약: [I01 구현 보고](I01_UNIFIED_GUIDE.md)
- 실제 자료·권리·기준선: [인벤토리](INVENTORY_AND_BASELINE.md)
- 전체 단계와 인터페이스: [통합 계획](UNIFIED_IMPLEMENTATION_PLAN.md)
- 실제 검사 상태: [인수표](UNIFIED_ACCEPTANCE_TEST_MATRIX.csv)

실제 고유 가이드는 기존 mini-kit 1건이다. 기존 레코드 내용 해시 `09f69cbb475d07ed85296e75e8180a61c59e8dc9795f308ddc1a44b160d63e2d`와 70/120/280/130 배분을 유지한다. 예전 852개 통과는 v3를 포함한 과거 브랜치 기록이므로 현재 I01 검사 수와 혼용하지 않는다.

이전 callback 방식은 순수 사전 계산 점수 계약으로 교체했다. 새 검색은 기본 OFF, 기존 mini-kit는 LEGACY_EXACT와 UNKNOWN 계수 정책을 구분한다. API/화면/Writer 연결과 운영 배포는 아직 수행하지 않았다.
