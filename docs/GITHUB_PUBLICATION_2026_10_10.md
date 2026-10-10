# GitHub 업로드와 CI 점검 — 2026-10-10

저장소: https://github.com/yoon-chan-hyeok/career-harness · 비공개 · main

사용자가 명시적으로 GitHub 업로드를 요청했다. 기존 연결 원격은 없었고 GitHub 계정 yoon-chan-hyeok을 확인해 저장소를 만들었다. 최초 업로드 커밋은 `bb47f4b9fbf0f87611986da6f3dd8b6b7cb2dfb1`이며 원격 main과 로컬 해시 일치를 확인했다. API 키·로컬 접속 설정·개인 DB·개인 원문·작업 임시 파일은 제외했다. 이력 7개 커밋과 현재 업로드 대상의 경로·비밀정보 검사도 통과했다.

첫 원격 CI에서 로컬 환경과 별개인 두 문제가 확인되어 수정했다.

- Python 3.12의 새 검사 환경에는 setuptools가 기본 설치되지 않는다. 배포 wheel을 실제 빌드하는 검사에서 사용하므로 개발 의존성에 명시했다. 한글 글꼴과 오프라인 토크나이저·라이선스가 배포 파일에 실제 포함되는지도 확인한다.
- source-map-js를 1.2.2로, Next.js와 대응 ESLint 설정을 15.5.27로 갱신했다. [source-map-js 권고](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), [Next.js 권고](https://github.com/advisories/GHSA-4jqv-mc3x-m676)의 수정 버전이다.

실행 의존성의 `npm audit --omit=dev --audit-level=high`는 수정 후 통과했다. 모든 의존성 경고가 없다는 뜻은 아니다. Transformers.js 3 계열의 Node 전용 간접 의존성에 moderate 경고가 남아 있고, 개발용 ESLint의 braces 계열에도 high 경고가 남아 있다. 자동 권고가 제안하는 메이저 업그레이드/다운그레이드는 적용하지 않았다. 별도 호환성 확인이 필요하다.

코드 업로드는 실제 AI 연결·Vercel/Supabase 운영 배포와 다르다. 기능별 완료 범위는 [최신 구현 기록](FINAL_REVIEW_PROGRESS_2026_10_10.md)을 참고한다. CI의 최종 결과는 GitHub Actions에서 해당 커밋 기준으로 확인한다.
