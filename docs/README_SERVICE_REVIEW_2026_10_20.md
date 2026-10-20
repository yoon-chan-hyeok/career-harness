# Career Harness 서비스 소개 검증 — 2026-10-20

범위: Career Harness README와 소개 영상, 별도 포트폴리오 웹페이지. 다른 프로젝트 README와 GitHub 프로필 README는 비교·확인 대상으로만 사용하며 변경하지 않는다.

## 비교에서 확인한 점

다른 프로젝트의 공개 README는 문제, 바꾼 판단, 결과와 해석 범위를 구분한다. Career Harness README도 같은 기준으로 정리하되, 처음 방문한 사람이 서비스와 시작 방법을 먼저 이해하도록 순서를 바꿨다.

- 맨 위에 실제 홈페이지와 작업실 링크를 분리하고, 홈페이지로 연결되는 실제 구현 화면을 배치했다.
- 이용 대상, 기능, 남는 결과물, 사용 흐름, 체험 순서를 앞에 설명한다.
- 사용자 승인·근거 검증·보관과 실제 제출의 차이를 유지한다.
- 반복된 CI·운영 이력과 개발 상세는 아래쪽 또는 별도 문서로 옮겼다.
- 가상 기능 예시, 제작자의 실제 경험을 재구성한 영상, 합성 자료의 실제 앱 화면을 구분한다.
- 개인 전체 자료로 지원서 한 건을 완성하는 품질 인수는 미통과라고 남긴다.

## 실제 사례의 사실 대조

| 확인한 표현 | 대조 근거 | 판정 |
|---|---|---|
| 긴 로그의 여러 탐색 방식에서 성공 조건을 먼저 정하는 방식으로 전환 | [TSR-Loc README](https://github.com/yoon-chan-hyeok/multi-agent-failure-localization#3-분할-실험에서-성공-명세로) | 영상에 수치 없는 판단 전환 사례로 사용 |
| 단계 일치율 8.15% → 38.59% | [공개 결과표](https://github.com/yoon-chan-hyeok/multi-agent-failure-localization/blob/main/results/who_and_when_main.csv) | Direct/No-GT 184건 기준과 일치. Career Harness의 성능으로 쓰지 않음 |
| TSR-Loc이 모든 비교 방법보다 우수하거나 SOTA라는 표현 | [TSR-Loc 해석 범위](https://github.com/yoon-chan-hyeok/multi-agent-failure-localization#10-해석-범위와-한계) | 사용하지 않음. A2P와 유의한 차이 없음, Pro 공식 전용 prompt가 수치상 높음 |
| RAG 성능 저하 탐지의 약 80% | [고정 전이 결과표](https://github.com/yoon-chan-hyeok/temporal-rag-drift/blob/main/results/core4_ml/frozen_future_model_summary.csv) | Extra Trees 47/60=78.3%, GAM 48/60=80.0%로 모델을 구분해야 함. 영상·서비스 소개의 일반 효과로 사용하지 않음 |
| 임베딩만으로 OCR 오류를 일관되게 개선 | [OCR README](https://github.com/yoon-chan-hyeok/ocr-quality-monitoring#5-검증-결과와-달라진-판단) | 주장하지 않음. 기본 confidence와 일부 보완, 숫자 치환 실패를 구분 |
| 셔틀로 귀가 시간이 줄었다거나 출결 정확도가 향상됐다는 수치 | [교통 분석](https://github.com/yoon-chan-hyeok/yeouido-festival-mobility-analysis#해석-범위), [출결 검증 범위](https://github.com/yoon-chan-hyeok/face-attendance-system#확인한-범위와-남은-평가) | 주장하지 않음. 운영 제안과 판정 구현을 효과 검증과 구분 |
| 문항별 구성·근거·메모를 실제 Writer에 연결 | [공개 인수 기록](WRITING_PLAN_2026_10_17.md) | 구현·합성 검증 범위와 일치. 개인 전체 생성 품질 검증으로 확대하지 않음 |

공개 결과표와 문서의 일치 여부를 확인한 것이며, 외부 모델을 다시 호출하거나 연구 전체 실험을 재실행한 것은 아니다.

## 연결과 영상 확인

실제 홈페이지 https://career-harness-web.vercel.app/ 와 작업실 https://career-harness-web.vercel.app/workspace 에서 HTTP 200을 확인했다. GitHub의 저장소 홈페이지 정보도 실제 서비스 홈을 가리키도록 연결한다.

38초 영상은 1080×1920·60fps, 전체 2,280프레임 디코딩, 12개 장면·자막, 48kHz AAC stereo, MP4 faststart를 확인했다. 개인 원문을 복사하지 않았고 원래 AI 응답의 녹화처럼 표시하지 않았다. 실제 앱 화면은 합성 QA 자료다. 수치·합격·시간 절감 효과를 추가하지 않았다.

코드·영상·공개 반영 결과는 IMPLEMENTATION_STATUS.json의 founder_case_film_2026_10_20 항목으로 기록한다.

Career Harness 공개 소스 eee5b0f와 CI39376670858 backend·frontend 성공을 확인했다. 별도 포트폴리오 페이지는 3235bfc, GitHub Pages 배포39377130333 성공이며 서비스 홈페이지·영상·한국어 자막을 연결했다. 다른 프로젝트 README와 프로필 README는 원격 변경이 없다.

