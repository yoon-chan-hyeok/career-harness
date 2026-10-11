// Export only public, synthetic presentation assets. No API or account data.
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
const destination = process.argv[2];
if (!destination || !path.isAbsolute(destination)) throw new Error("Use the absolute registered Site directory.");
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
if (path.resolve(destination) === root || root.startsWith(path.resolve(destination) + path.sep)) throw new Error("Use a separate Site directory.");
const manifestPath = path.join(destination, ".openai", "hosting.json");
const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (!manifest.project_id) throw new Error("Register and persist the Site identity first.");
const source = path.join(root, "frontend/public/showcase");
const output = path.join(destination, "dist/showcase");
mkdirSync(output, { recursive: true });
for (const name of ["style.css", "demo.js", "icon.svg", "social.png", "career-harness-demo.mp4"]) copyFileSync(path.join(source, name), path.join(output, name));
let html = readFileSync(path.join(source, "index.html"), "utf8").replace('data-mode="workspace"', 'data-mode="preview"');
// Hosted static copy remains useful without JavaScript and never links to a
// non-existent /workspace route. The local app keeps its actual workspace CTA.
html = html.replaceAll('data-workspace href="/workspace"', 'data-workspace href="#start"');
html = html.replaceAll('작업실 열기', '시작 방법 보기').replaceAll('내 경험으로 시작하기', '시작 방법 보기');
html = html.replace('먼저 경험을 등록하고, 지원하고 싶은 공고를 가져오세요.<br>직접 작성으로 시작하거나, 내 AI 제공자를 연결할 수 있습니다.', '공개 서비스 연결을 준비 중입니다. 위 데모를 체험하거나 GitHub 실행 안내에 따라 내 컴퓨터에서 작업실을 열 수 있습니다.');
writeFileSync(path.join(destination, "dist/index.html"), html);
writeFileSync(path.join(output, "index.html"), html);
writeFileSync(manifestPath, JSON.stringify({ ...manifest, static: { directory: "dist" } }, null, 2) + "\n");
writeFileSync(path.join(destination, "README.md"), "# Career Harness 소개\n\n가상 자료만 사용하는 정적 제품 소개입니다. 계정·AI·저장 API는 포함하지 않습니다.\n\n원본: https://github.com/yoon-chan-hyeok/career-harness\n\n원본 저장소의 scripts/prepare-showcase-site.mjs로 지정한 소개 자산만 복사합니다.\n");
console.log("Public synthetic presentation assets prepared.");
