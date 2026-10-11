/* Standalone, synthetic presentation. No API, persistence, or AI requests. */
(() => {
  if (new URLSearchParams(location.search).has("film")) document.body.classList.add("film");
  const phases = [
    { title: "공고에서 본업 찾기", user: "이 공고는 실제로 어떤 일을 하는 직무일까?", answer: "기술 목록에 앞서, 입사 후 만들어야 할 산출물부터 정리해 볼게요.", label: "직무 분석", heading: "데이터를 현장의 판단으로", items: ["핵심 산출물 · 의사결정용 분석 보고서", "주요 역량 · 문제 정의와 가설 검증", "확인할 공백 · 실제 운영 경험"], foot: "공고 원문을 기준으로 확인", caption: "공고의 키워드보다, 맡게 될 일부터.", description: "기업·직무 자료를 확인하고, 실제 산출물과 핵심 역량을 정리합니다. 확인되지 않은 채용 배경은 가설로 남깁니다.", docs: [["직무 분석", "공고 원문 연결"]] },
    { title: "경험을 근거로 연결하기", user: "내 문서 분류 프로젝트가 이 직무의 근거가 될까?", answer: "실제로 한 일과 직무에서 요구하는 일을 대조해 볼게요. 아직 증명하지 못한 범위도 함께 남깁니다.", label: "경험 · 근거", heading: "실험은 근거로, 운영은 공백으로", items: ["직접 수행 · 평가 기준과 실험 설계", "연결 역량 · 결과를 비교하고 판단한 경험", "미확인 범위 · 실제 서비스 운영 성과"], foot: "원자료 · 본인 기여 · 수치 범위를 확인", caption: "비슷한 기술을 썼다는 이유만으로 연결하지 않습니다.", description: "원자료와 실제 기여 범위를 확인하고, 직접 근거·인접 근거·근거 없음으로 직무와의 거리를 구분합니다.", docs: [["직무 분석", "확인 완료"], ["직무별 근거", "원자료 연결"]] },
    { title: "지원 전략 직접 승인하기", user: "이 지원에서는 어떤 강점을 먼저 보여줄까?", answer: "문제를 정의하고, 실험 결과를 다음 판단으로 연결한 경험을 중심에 둘 수 있어요. 이 방향으로 진행할지 직접 확인해 주세요.", label: "지원 전략 · 승인 대기", heading: "맡길 수 있는 일을 한 문장으로", items: ["핵심 메시지 · 근거로 판단을 바꾸는 분석", "증명할 경험 · 평가 실험과 적용 범위 조정", "대응할 공백 · 실제 운영 경험은 과장 없이"], foot: "전략을 직접 확인한 뒤 다음 단계로", caption: "설득의 방향은 내가 결정합니다.", description: "직무와 경험을 바탕으로 지원 전략을 제안합니다. 문항마다 전달할 메시지를 나누고, 사용자 승인을 거쳐 작성합니다.", docs: [["직무 분석", "확인 완료"], ["직무별 근거", "원자료 연결"], ["지원 전략", "직접 승인 필요"]] },
    { title: "자소서와 레쥬메 함께 작성하기", user: "판단을 바꾼 이유가 드러나게 써줘. 이력서도 정리해 줘.", answer: "자소서는 판단의 이유를, 이력서는 산출물과 기여를 먼저 보여줄게요. 각각의 주장에는 선택한 근거를 연결합니다.", label: "작성 중", heading: "하나의 경험, 두 가지 읽기 방식", items: ["자소서 · 관찰 → 판단 → 행동 → 배운 점", "레쥬메 · 산출물 → 기여 → 검증 근거", "문항별 초안과 변경 이력을 따로 보관"], foot: "대화 왼쪽의 흐름과 오른쪽 문서가 연결", caption: "대화하며 쓰고, 문서는 따로 정리합니다.", description: "문항의 의도에 맞춰 자소서를 작성하고, 직무와 가까운 경험부터 이력서에 배치합니다. 초안과 버전은 문서 보관함에 남습니다.", docs: [["지원 전략", "승인 완료"], ["자기소개서 · 1번", "초안 v1"], ["직무별 레쥬메", "초안 v1"]] },
    { title: "과장을 확인하고 수정하기", user: "‘운영 비용을 줄였다’는 표현이 정확한지 확인해 줘.", answer: "현재 근거에는 운영 비용을 측정한 기록이 없어요. 실험에서 확인한 범위로 문장을 좁히고, 수정 내용을 직접 검토해 주세요.", label: "검수 · 수정 제안", heading: "강한 문장에도, 분명한 경계", items: ["확인할 표현 · 측정하지 않은 비용 절감", "수정 방향 · 검토 우선순위 제안 가능성", "면접 확인 · 실제 사용자와 배포 범위"], foot: "수정 제안 확인 → 반영 → 다시 검수", caption: "유창한 문장보다, 면접에서 설명할 수 있는 문장.", description: "사실·수치·기여 범위를 점검하고 질문에 답합니다. 수정 결과를 다시 검수한 후, 사용자가 최종본을 잠급니다.", docs: [["자기소개서 · 1번", "수정안 v2"], ["직무별 레쥬메", "검수 중"], ["검수 답변", "근거 범위 확인"]] },
    { title: "최종본 보관과 면접 준비", user: "이 내용으로 보관하고, 면접에서 받을 질문도 정리해 줘.", answer: "직무와의 일치, 지원 이유, 경험의 근거를 직접 확인한 뒤 최종본을 보관합니다. 보관한 답변을 면접 준비에 이어갈 수 있어요.", label: "최종본 · 아직 미제출", heading: "그때의 문서와 근거를 함께", items: ["자소서·레쥬메 · 확정한 버전 보관", "면접 준비 · 당시 주장과 답변을 참조", "실제 제출 완료는 별도로 직접 확인"], foot: "최종본 보관 ≠ 실제 지원서 제출", caption: "지원의 끝에서, 다음 준비의 시작으로.", description: "확정한 문서와 근거를 당시 상태로 보관합니다. 실제 제출 확인은 별도이며, 면접 자료는 보관한 내용에서 이어집니다.", docs: [["자기소개서 · 최종", "최종본 보관"], ["레쥬메 · 최종", "최종본 보관"], ["면접 준비", "보관본에서 연결"]] },
  ];
  let current = 0;
  let timer = null;
  const byId = (id) => document.getElementById(id);
  const reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  function show(index) {
    current = (index + phases.length) % phases.length;
    const phase = phases[current];
    const values = { "stage-title": phase.title, "user-message": phase.user, "assistant-message": phase.answer, "result-label": phase.label, "result-title": phase.heading, "result-foot": phase.foot, "caption-title": phase.caption, "caption-text": phase.description, "caption-number": String(current + 1).padStart(2, "0"), "phase-count": `PHASE ${String(current + 1).padStart(2, "0")} / 06`, "document-count": String(phase.docs.length) };
    Object.entries(values).forEach(([id, text]) => { byId(id).textContent = text; });
    byId("result-items").replaceChildren(...phase.items.map((text) => { const li = document.createElement("li"); li.textContent = text; return li; }));
    byId("storage-list").replaceChildren(...phase.docs.map(([name, status], i) => {
      const row = document.createElement("div"); row.className = "storage-item" + (i === phase.docs.length - 1 ? " current" : "");
      const icon = document.createElement("span"); icon.className = "file-icon"; icon.textContent = "▤"; icon.setAttribute("aria-hidden", "true");
      const detail = document.createElement("div"); const title = document.createElement("strong"); title.textContent = name; const subtitle = document.createElement("small"); subtitle.textContent = status; detail.append(title, subtitle); row.append(icon, detail); return row;
    }));
    document.querySelectorAll("[data-phase]").forEach((button) => { button.setAttribute("aria-pressed", String(Number(button.dataset.phase) === current)); });
    const scene = byId("scene"); scene.classList.remove("scene-enter");
    if (!reduced.matches) { void scene.offsetWidth; scene.classList.add("scene-enter"); }
  }
  function stop() { clearInterval(timer); timer = null; byId("play").textContent = "▶ 자동 재생"; byId("play").setAttribute("aria-label", "단계 자동 재생"); byId("play").setAttribute("aria-pressed", "false"); }
  function play() { if (timer) { stop(); return; } byId("play").textContent = "Ⅱ 일시 정지"; byId("play").setAttribute("aria-label", "단계 자동 재생 일시 정지"); byId("play").setAttribute("aria-pressed", "true"); timer = setInterval(() => show(current + 1), 4800); }
  document.querySelectorAll("[data-phase]").forEach((button) => button.addEventListener("click", () => { stop(); show(Number(button.dataset.phase)); }));
  byId("play").addEventListener("click", play);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stop(); });
  reduced.addEventListener("change", () => { if (reduced.matches) stop(); });
  window.addEventListener("pagehide", stop);
  // The hosted introduction is deliberately independent from private workspaces.
  if (document.body.dataset.mode === "preview") {
    document.querySelectorAll("[data-workspace]").forEach((link) => { link.href = "#start"; link.textContent = "시작 방법 보기 ↗"; });
    byId("launch-copy").textContent = "공개 서비스 연결을 준비 중입니다. 지금은 위 데모로 흐름을 체험하거나 GitHub의 실행 안내에 따라 내 컴퓨터에서 작업실을 열 수 있습니다.";
  }
  show(0);
})();
