# 의존성 경고 대조 — 2026-10-13

코드 `a8b1b96`의 원격 검사는 통과했지만 의존성 취약점 0건 판정은 아니다. 설치 로그의 10건은 독립적인 취약점 10개가 아니라, 아래 두 권고가 전파된 의존성 항목 10개다. 전체 감사는 high 5 / moderate 5, 배포 의존성 감사는 moderate 5다. 개인정보나 공격 발생 증거를 발견한 기록은 아니다.

| 실제 권고 | 설치 경로 | 확인 결과 |
|---|---|---|
| braces 깊은 중괄호 패턴의 서비스 거부 | eslint-config-next → Next ESLint plugin → fast-glob → micromatch → braces 3.0.3 | 개발 검사 의존성. 당시 공식 권고의 수정 버전 없음, npm 최신도 3.0.3 |
| sprintf-js 포맷 정밀도 값의 서비스 거부 | Transformers.js 3.8.1 → onnxruntime-node 1.21.0 → global-agent → roarr → sprintf-js 1.1.3 | Node 추론 패키지의 설치용 프록시/로깅 경로. 당시 공식 권고의 수정 버전 없음, npm 최신도 1.1.3 |

공식 권고: [braces GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm), [sprintf-js GHSA-hp3w-g68c-fv3c](https://github.com/advisories/GHSA-hp3w-g68c-fv3c). 취약 입력이 실제로 해당 함수에 도달해야 하는 문제이며, 설치되어 있다는 사실과 서비스의 공격 가능성은 동일하지 않다.

현재 소스의 임베딩은 `frontend/app/korean-embeddings.ts`의 클라이언트 전용 동적 import와 고정된 E5 모델을 사용한다. 설치된 `onnxruntime-node/script/install.js`가 `global-agent`를 불러오는 것을 확인했다. 현재 로컬 standalone의 최상위 node_modules에는 braces·sprintf-js·global-agent가 없고 onnxruntime-node는 있다. **이 파일 위치 관찰만으로 전체 번들에서의 코드 부재나 공격 불가능을 증명하지 않는다.** 서버 추적 파일·브라우저 번들·실제 요청 도달 경로 확인은 후속 작업이다.

`npm audit`는 eslint-config-next를 14.2.35로 변경하거나 Transformers.js를 4.3.1로 변경하는 강제 수정안을 표시했다. 현재 Next 15.5.27과의 일치, 임베딩 벡터·기존 색인 호환성을 검증하지 않은 채 적용하지 않았다. 의존성 파일과 잠금 파일은 이번 점검에서 변경하지 않았다.

후속 작업은 실제 번들·호출 경로를 확인하고, 취약 경로를 제거할 수 있는 호환 가능한 상위 의존성 변경을 조사·검증하는 것이다. 실제 모델 출력, 기존 검색 색인, 브라우저 추론과 배포 빌드까지 확인해야 한다. 수정된 상위 버전이나 검증된 경로 제거가 없는 상태를 보안 경고 해소로 표시하지 않는다.

로컬 원본 감사 JSON은 `work/dependency-audit-2026-10-13.json`에 보관하며 공개 저장소에는 포함하지 않는다. 공식 권고와 npm 메타데이터는 이후 바뀔 수 있으므로 적용 시 다시 확인한다.
