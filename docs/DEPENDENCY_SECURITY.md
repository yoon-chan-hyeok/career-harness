# 프런트엔드 의존성 보안 기록 — 2026-10-04

실제 frontend Docker 빌드의 설치 단계에서 npm 감사가 9개 패키지 경고(높음 8, 보통 1)를 보고했다. 경고 개수는 독립된 취약점 개수나 이 서비스에서 확인한 공격 개수와 같지 않다.

## 수정한 실행 의존성

`frontend/package.json`의 명시적 overrides와 잠금 파일을 함께 수정했다. Next.js 15와 E5 모델·Transformers.js 3의 현재 동작을 유지하고, 그 아래의 이미지/CSS 처리 라이브러리를 수정 버전으로 통일했다. 광범위한 강제 major 업그레이드는 수행하지 않았다.

| 라이브러리 | 실제 수정 버전 | 공식 근거 |
|---|---|---|
| Sharp | 0.35.5 | [libvips 권고](https://github.com/advisories/GHSA-f88m-g3jw-g9cj), [libheif 권고 및 0.35.4 수정](https://github.com/advisories/GHSA-rgj7-g3m4-5g8c) |
| PostCSS | 8.5.28 | [8.5.23에서 수정된 source map 파일 읽기 권고](https://github.com/advisories/GHSA-fxqj-rqcc-2cmp) |

Sharp의 Node 최소 요구는 20.9다. 실제 Docker Node 22.23.3과 Windows Node 24.14.1에서 설치를 확인했고, Windows에서는 공개 native binary로 합성 PNG 생성도 성공했다. patched Docker 이미지에서도 실제 Sharp 0.35.5·PostCSS 8.5.28과 화면·PDF worker·다운로드를 확인했다. 이 이미지는 이후 새 UI와 다단계 Docker 변경 전에 만든 검사 기록이다. 최신 전체 소스 인수는 추가 업그레이드 기록에서 확인한다.

`npm audit --omit=dev --json`은 확인 시점에 프로덕션 의존성 경고 0개였다. CI에도 `npm audit --omit=dev --audit-level=high`를 추가했다. 이 결과는 외부 감사 데이터의 현재 범위이며 모든 보안 문제의 부재를 증명하지 않는다. 로컬 검사 증거는 `work/fullstack-container-verification/npm-audit-production-after.json`에 있다. 실제 원격 CI는 저장소 연결 뒤 실행해야 한다.

## 남은 개발 도구 권고

전체 의존성 감사에는 Next ESLint→fast-glob→micromatch→braces 경로의 패키지 경고 5개가 남는다. [braces 공식 권고](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm)는 3.0.3 이하에 대한 수정 버전을 제공하지 않는다.

이 경로는 lint의 프로젝트 경로 설정을 처리한다. 현재 ESLint 설정에는 `settings.next.rootDir`가 없고, 문서·대화·검색 입력을 이 glob 함수에 전달하는 앱 코드는 없다. 그러나 전체 감사의 경고를 없다고 기록하거나 실행 경로 검토만으로 upstream 문제가 수정됐다고 판단하지 않는다. `npm-audit-all-after.json`에 원래 경고를 보존한다.

프런트엔드 Docker를 builder와 standalone runner로 나누고 runner를 `nextjs` 일반 사용자로 실행하도록 수정했다. 최신 새 이미지에서 실제 UID 1001, Sharp 0.35.5·PostCSS 8.5.28, eslint/braces/micromatch/fast-glob 및 전체 원본의 제외를 확인했다. 실제 화면·관리자 권한·경험 선택·API·모바일 흐름도 통과했다. 증거는 `work/expanded-upgrades-qa/runtime.json`과 `browser-acceptance.json`에 있다. 향후 공식 수정이 제공되면 lint 도구도 별도로 갱신한다.
