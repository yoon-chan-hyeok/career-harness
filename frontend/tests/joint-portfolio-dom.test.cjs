/* eslint-disable @typescript-eslint/no-require-imports */
const { test, before, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const React = require("react");
let dom, root, container, Component;
before(async () => {
  const { JSDOM } = await import("jsdom");
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://synthetic.test" });
  global.window = dom.window; global.document = dom.window.document; global.HTMLElement = dom.window.HTMLElement;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, "../app/joint-portfolio-panel.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, { exports, require, console, Error }); Component = exports.JointPortfolioPanel;
});
afterEach(async () => { if (root) await React.act(async () => root.unmount()); root = null; document.body.innerHTML = ""; });
function fixture() {
  return { application_id: "app-a", input_revision: "a".repeat(64), decision_revision: "b".repeat(64),
    questions: [{ id: "q1", text: "직무역량" }, { id: "q2", text: "협업" }],
    candidates: [{ evidence_id: "own-e1", title: "본인 검증 경험", classification: "DIRECT", eligibility: "ELIGIBLE", limitations: [], metrics: [] },
      { evidence_id: "held-e2", title: "수행 범위 미확인", classification: "ADJACENT", eligibility: "HOLD", limitations: ["본인 수행 확인"], metrics: [] }],
    holds: [], notice: "검토 제안", strategy: { positioning: "연구원", assignment_statement: "검증 보고서 작성" },
    proposal: { id: "proposal-a", version: 2, current: true, status: "ACTIVE", data: {
      personas: [{ candidate_id: "p1", text: "검증 연구원", limitation: "수행 범위 안에서" }, { candidate_id: "p2", text: "실험 설계자", limitation: "현재 근거에서" }],
      items: [1, 2].map(i => ({ question_id: "q" + i, identity_role: "역할" + i, primary_message: "메시지" + i,
        evidence_ids: ["own-e1"], evidence_role: "수행" + i, metric_ids: [], climax: "장면" + i })) } },
    decision: null, persona: null, portfolio: null };
}
async function render(state = fixture(), override) {
  const calls = [], dirtyState = { current: false };
  const request = override || (async (url, body) => {
    if (!body) return structuredClone(state);
    calls.push({ url, body });
    if (url.endsWith("/decide")) {
      state.decision = { id: "decision-a", version: 1, current: true, status: "ACTIVE", data: { disposition: body.disposition, items: body.items } };
      state.persona = { id: "persona-a", current: true, status: "ACTIVE", data: { text: body.persona_text } };
      state.portfolio = { id: "portfolio-a", status: "ACTIVE" };
    } else if (url.endsWith("/approve-strategy")) state.persona.status = "LOCKED";
    else if (url.endsWith("/approve-portfolio")) state.portfolio.status = "LOCKED";
    return { id: "decision-a" };
  });
  const props = { workspaceId: "app-a", revisionKey: "initial", request, onSaved: async () => {}, ai: true, dirtyState };
  container = document.createElement("div"); document.body.appendChild(container);
  root = require("react-dom/client").createRoot(container);
  await React.act(async () => root.render(React.createElement(Component, props)));
  return { state, props, calls, dirtyState };
}
const button = text => [...container.querySelectorAll("button")].find(node => node.textContent.includes(text));
async function click(node) { await React.act(async () => node.click()); }
async function edit(node, value) {
  await React.act(async () => {
    const proto = node.tagName === "SELECT" ? dom.window.HTMLSelectElement.prototype : dom.window.HTMLTextAreaElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(node, value);
    node.dispatchEvent(new dom.window.Event("input", { bubbles: true })); node.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  });
}
test("material editor posts only chosen own IDs and separate approvals run in order", async () => {
  const f = await render();
  const held = [...container.querySelectorAll("label")].find(node => node.textContent.includes("수행 범위 미확인")).querySelector("input");
  assert.equal(held.disabled, true);
  await edit(container.querySelector('[aria-label="1번 핵심 메시지"]'), "직접 고친 실제 메시지");
  assert.equal(f.dirtyState.current, true);
  await click(button("선택 저장"));
  const body = f.calls[0].body;
  assert.equal(body.proposal_id, "proposal-a"); assert.equal(body.proposal_version, 2);
  assert.deepEqual([...body.items[0].evidence_ids], ["own-e1"]);
  assert.equal(body.items[0].primary_message, "직접 고친 실제 메시지");
  assert.equal("approved" in body, false); assert.equal("owner_id" in body, false); assert.equal("guide" in body, false);
  assert.equal(f.dirtyState.current, false);
  assert.equal(button("모든 문항 배분 확인 후 승인").disabled, true);
  await click(button("Persona·기존 전략"));
  assert.equal(button("모든 문항 배분 확인 후 승인").disabled, false);
  await click(button("모든 문항 배분 확인 후 승인"));
  assert.deepEqual(f.calls.slice(1).map(call => call.url.split("/").at(-1)), ["approve-strategy", "approve-portfolio"]);
});
test("hold is an explicit reason event with no persona or evidence approval", async () => {
  const f = await render();
  await edit(container.querySelector("select"), "HOLD");
  assert.equal(button("거절·보류 기록").disabled, true);
  await edit(container.querySelector('[aria-label="선택 이유"]'), "원자료를 확인하겠습니다.");
  await click(button("거절·보류 기록"));
  assert.equal(f.calls[0].body.disposition, "HOLD");
  assert.equal(f.calls[0].body.persona_text, ""); assert.equal(f.calls[0].body.items.length, 0);
  assert.equal(button("Persona·기존 전략"), undefined);
});
test("409 keeps material inputs and does not automatically retry", async () => {
  const state = fixture(); let writes = 0;
  const f = await render(state, async (url, body) => { if (!body) return state; writes++; throw new Error("버전 충돌409"); });
  await edit(container.querySelector('[aria-label="1번 핵심 메시지"]'), "보존할 입력");
  await click(button("선택 저장"));
  assert.equal(writes, 1); assert.match(container.querySelector('[role="alert"]').textContent, /409/);
  assert.equal(container.querySelector('[aria-label="1번 핵심 메시지"]').value, "보존할 입력");
  assert.equal(f.dirtyState.current, true);
});
test("external revision preserves edits until explicit discard and refresh", async () => {
  const f = await render();
  await edit(container.querySelector('[aria-label="선택한 Persona"]'), "미저장 Persona");
  f.state.decision_revision = "c".repeat(64);
  await React.act(async () => root.render(React.createElement(Component, { ...f.props, revisionKey: "changed" })));
  assert.equal(container.querySelector('[aria-label="선택한 Persona"]').value, "미저장 Persona");
  assert.match(container.textContent, /편집 내용은 보존/);
  await click(button("입력 버리고"));
  assert.equal(container.querySelector('[aria-label="선택한 Persona"]').value, "검증 연구원");
  assert.equal(f.dirtyState.current, false);
});
