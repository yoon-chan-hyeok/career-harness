# 자동 검사 실행 환경 보완 — 2026-10-13

문서 간 검수 코드 `ba8cf5b`의 [GitHub 자동 검사](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/38352487730)가 성공했다. Python 698개와 별도 실제 PostgreSQL 7개, 전체 마이그레이션 왕복/check, 개인정보 차단, 프런트 26개·빌드·의존성 검사를 확인했다. 해당 실행에 남은 오래된 액션 런타임과 Ubuntu 자동 전환 경고를 해결하기 위해 CI 설정을 보완했다.

| 항목 | 변경 |
|---|---|
| 공식 액션 | checkout v7.0.1, setup-python v7.0.0, setup-node v7.1.0의 실제 릴리스 커밋 SHA 고정 |
| 실행 기반 | GitHub 호스팅 ubuntu-24.04 명시 |
| 권한 | GITHUB_TOKEN은 contents: read만 허용 |
| 접속 정보 | checkout 이후 인증정보 보존 비활성화 |
| 패키지 캐시 | 새 setup-node의 자동 npm 캐시 비활성화로 기존 검사 방식 유지 |
| Windows 검증 | 임시 경로 이름을 줄이고 기존 경로 재사용을 거부해 가상 Git 검사에서 발생한 파일 길이 제한 해결 |

공식 릴리스의 태그가 가리키는 커밋과 각 action.yml의 node24 실행 설정을 확인했다. 앱의 Python 3.12와 Node 22 설정, PostgreSQL 검사·마이그레이션·프라이버시·빌드 조건은 유지한다. 검증 워크플로만 변경하며 운영 배포·Vercel/Supabase 자격증명 연결 완료를 의미하지 않는다.

근거: [checkout 릴리스](https://github.com/actions/checkout/releases/tag/v7.0.1), [setup-node 릴리스](https://github.com/actions/setup-node/releases/tag/v7.1.0), [setup-python 릴리스](https://github.com/actions/setup-python/releases/tag/v7.0.0), [공식 runner 이미지](https://github.com/actions/runner-images). 최신 설정의 실제 원격 검사 결과는 IMPLEMENTATION_STATUS.json의 ci_refresh_2026_10_13에 기록한다.

전체 명세·여섯 참고 자료 인수와 실제 무료 AI/공개 서비스 운영 검증은 계속 남아 있다.

Windows 경로 변경은 Git의 전역 설정이나 개인자료 차단 조건을 바꾸지 않았다. 짧은 경로만 적용한 기존 개인정보 검사 14개를 모두 통과했다. 화면 파일 잠금은 여전히 실행 중인 해당 화면을 확인해 멈춘 뒤 빌드하는 절차가 필요하다.

검증 완료: 코드 `3c6354d`의 [새 환경 자동 검사](https://github.com/yoon-chan-hyeok/career-harness/actions/runs/38353112051)에서 Python 698개, 별도 실제 PG 7개, 전체 마이그레이션 왕복/check, 개인정보 차단과 프런트 26개·빌드·의존성 검사까지 성공했다. 두 작업의 annotation은 0개로 확인했다. 성공 기록을 추가한 문서 커밋은 이 검증 소스와 구별한다.
