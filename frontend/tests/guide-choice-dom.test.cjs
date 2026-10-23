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
  global.window = dom.window;
  global.document = dom.window.document;
  global.HTMLElement = dom.window.HTMLElement;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, "../app/question-guide-choice.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, { exports, require, console, Error });
  Component = exports.QuestionGuideChoice;
});
afterEach(async () => {
  if (root) await React.act(async () => root.unmount());
  root = null;
  document.body.innerHTML = "";
});
function fixture() {
  return {
    question_contract: { raw_text: "전문역량과 본인의 수행 근거를 설명하세요.", required_demands: [], excluded_topics: [],
      length: { maximum: 600, minimum: null, unit: "CHARACTERS", spaces: "UNKNOWN", newlines: "UNKNOWN", title: "UNKNOWN", encoding: "UNKNOWN" } },
    contract_state_revision: "a".repeat(64), needs_reconfirmation: false, catalog_status: "CONFIGURED",
    selection_revision: "b".repeat(64), selection: null,
    retrieval: { request_key: "c".repeat(64), candidates: [{ guide_id: "synthetic-guide", guide_version: 1,
      guide_snapshot_hash: "d".repeat(64), match_type: "ADVISORY_ANALOGY", intent: "판단·행동·검증 중심 구성",
      ranking_explanation: "현재 요구를 확인한 구조 참고 후보", source_ref: "https://example.com/guide",
      scope_transfer: true, count_policy_confirmation_required: true,
      suggested_allocation: ["역량", "상황", "행동", "결과"].map((content, i) => ({ content, suggested_budget: [70, 120, 280, 130][i] })) }],
      fallback: { intent: "현재 질문에 답하기", allocation: ["답변", "맥락", "근거", "마무리"].map(content => ({ content, suggested_budget: 150 })) } },
  };
}
async function render(state = fixture(), customRequest) {
  const calls = [], dirty = [], saved = [];
  const request = customRequest || (async (url, body) => {
    if (!body) return structuredClone(state);
    calls.push({ url, body });
    if (url.endsWith("/guide-choice")) {
      state.selection = { current: true, guide_id: body.guide_id, allocation_budgets: body.allocation_budgets };
    } else {
      state.question_contract = { ...state.question_contract, ...body };
    }
    return { id: "synthetic-choice" };
  });
  const props = { workspaceId: "app-a", questionId: "q-a", revision: "initial", request,
    onSaved: async () => saved.push(true), disabled: false, onDirtyChange: value => dirty.push(value) };
  container = document.createElement("div"); document.body.appendChild(container);
  const { createRoot } = require("react-dom/client"); root = createRoot(container);
  await React.act(async () => root.render(React.createElement(Component, props)));
  return { state, props, calls, dirty, saved };
}
const button = text => [...container.querySelectorAll("button")].find(node => node.textContent.includes(text));
async function click(node) { await React.act(async () => node.click()); }
async function edit(node, value) {
  await React.act(async () => {
    const proto = node.tagName === "TEXTAREA" ? dom.window.HTMLTextAreaElement.prototype : dom.window.HTMLInputElement.prototype;
    Object.getOwnPropertyDescriptor(proto, "value").set.call(node, value);
    node.dispatchEvent(new dom.window.Event("input", { bubbles: true }));
    node.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  });
}

test("actual React selection saves only ID/version/hash and budgets, then retains the chosen state", async () => {
  const result = await render();
  assert.match(container.textContent, /현재 회사의 공식 지침이 아닙니다/);
  await click(container.querySelectorAll('input[type="radio"]')[1]);
  await edit(container.querySelector('input[aria-label="역량 권장 분량"]'), "80");
  await edit(container.querySelector('input[aria-label="결과 권장 분량"]'), "120");
  assert.equal(result.dirty.at(-1), true);
  await click(button("이 구성과 분량으로 선택"));
  assert.equal(result.calls.length, 1);
  assert.equal(result.calls[0].body.guide_id, "synthetic-guide");
  assert.equal(result.calls[0].body.guide_version, 1);
  assert.deepEqual([...result.calls[0].body.allocation_budgets], [80, 120, 280, 120]);
  assert.equal("guide" in result.calls[0].body, false);
  assert.equal("approved" in result.calls[0].body, false);
  assert.equal(container.querySelectorAll('input[type="radio"]')[1].checked, true);
  assert.equal(container.querySelector('input[aria-label="역량 권장 분량"]').value, "80");
  assert.equal(result.saved.length, 1);
  assert.equal(result.dirty.at(-1), false);
});

test("editing a current requirement blocks guide choice until explicit form confirmation is saved", async () => {
  const result = await render();
  await edit(container.querySelector("textarea"), "본인 기여 비율");
  assert.equal(container.querySelectorAll("fieldset")[1].disabled, true);
  assert.equal(button("문항 기준 확인 저장").disabled, true);
  await click(container.querySelector('input[type="checkbox"]'));
  await click(button("문항 기준 확인 저장"));
  assert.equal(result.calls[0].body.confirmed, true);
  assert.deepEqual([...result.calls[0].body.required_demands], ["본인 기여 비율"]);
  assert.equal(container.querySelectorAll("fieldset")[1].disabled, false);
  assert.equal(result.dirty.at(-1), false);
});

test("server conflict keeps edited content and does not automatically repeat a save", async () => {
  const state = fixture(); let attempts = 0;
  const result = await render(state, async (_url, body) => {
    if (!body) return structuredClone(state);
    attempts++;
    throw new Error("문항·가이드 기준이 바뀌었습니다.");
  });
  await click(container.querySelectorAll('input[type="radio"]')[1]);
  await edit(container.querySelector('input[aria-label="역량 권장 분량"]'), "90");
  await edit(container.querySelector('input[aria-label="결과 권장 분량"]'), "110");
  await click(button("이 구성과 분량으로 선택"));
  assert.match(container.querySelector('[role="alert"]').textContent, /바뀌었습니다/);
  assert.equal(attempts, 1);
  assert.equal(container.querySelector('input[aria-label="역량 권장 분량"]').value, "90");
  assert.equal(result.dirty.at(-1), true);
  await click(button("입력 버리고 현재 기준 새로 불러오기"));
  assert.equal(result.dirty.at(-1), false);
});

test("an external revision does not erase unsaved requirements and invalid budget cannot submit", async () => {
  const result = await render();
  await edit(container.querySelector("textarea"), "입력 중인 요구");
  await React.act(async () => root.render(React.createElement(Component, { ...result.props, revision: "changed" })));
  assert.equal(container.querySelector("textarea").value, "입력 중인 요구");
  assert.match(container.querySelector('[role="alert"]').textContent, /입력은 유지/);
  await click(button("입력 버리고 현재 기준 새로 불러오기"));
  await edit(container.querySelector('input[aria-label="답변 권장 분량"]'), "600");
  assert.equal(button("이 구성과 분량으로 선택").disabled, true);
});
