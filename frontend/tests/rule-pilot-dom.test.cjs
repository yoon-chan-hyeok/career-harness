/* eslint-disable @typescript-eslint/no-require-imports */
const { test, before, afterEach } = require("node:test");
const assert = require("node:assert/strict");
const React = require("react");
const fs = require("node:fs"); const path = require("node:path"); const vm = require("node:vm"); const ts = require("typescript");
let root, container, dom, Component;
before(async () => {
  const { JSDOM } = await import("jsdom");
  dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "http://synthetic.test" });
  global.window = dom.window; global.document = dom.window.document; global.HTMLElement = dom.window.HTMLElement;
  global.IS_REACT_ACT_ENVIRONMENT = true;
  const exports = {};
  const source = ts.transpileModule(fs.readFileSync(path.join(__dirname, "../app/rule-pilot-panel.tsx"), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(source, { exports, require, console, Error }); Component = exports.RulePilotPanel;
});
afterEach(async () => { if (root) await React.act(async () => root.unmount()); root = null; document.body.innerHTML = ""; });
function fixture() {
  return { revision: "a".repeat(64), availability: "CONFIGURED", workspace_id: "app-a", counts: { indexed: 1, candidate_52: 0, unrefined_65: 0 },
    unavailable_adoptions: [], rules: [{ rule_id: "SYN-1", summary: "확인한 근거의 수치만 사용", source_package: "synthetic", candidate_52: false, unrefined_65: false,
      proof: "b".repeat(64), excerpt: "<script>synthetic source</script>", issue: null,
      contract: { version: 1, action: "CHECK_METRICS", gate: "SUPPORTED_METRICS", scope: "COVER", start_line: 2, end_line: 2 },
      states: { RuleSourceReview: null, RuleCodeEvaluation: null, RuleActivation: null } }] };
}
async function render(state = fixture(), custom) {
  const calls = [];
  const request = custom || (async (url, body) => {
    if (!body) return structuredClone(state);
    calls.push({ url, body });
    const key = url.endsWith("source-review") ? "RuleSourceReview" : url.endsWith("evaluate") ? "RuleCodeEvaluation" : "RuleActivation";
    state.rules[0].states[key] = { id: "record-" + key, current: true, data: { status: "PASSED", activation: url.endsWith("retire") ? "RETIRED" : "ACTIVE_SCOPED", rule_version: 1 } };
    state.revision = String(calls.length).repeat(64);
    return { id: "record-1" };
  });
  container = document.createElement("div"); document.body.appendChild(container);
  root = require("react-dom/client").createRoot(container);
  const props = { workspaceId: "app-a", revisionKey: "initial", request, onSaved: async () => {} };
  await React.act(async () => root.render(React.createElement(Component, props)));
  return { state, props, calls };
}
const button = text => [...container.querySelectorAll("button")].find(node => node.textContent.includes(text));
async function click(node) { await React.act(async () => node.click()); }
async function choose() {
  await React.act(async () => {
    const node = container.querySelector("select");
    Object.getOwnPropertyDescriptor(dom.window.HTMLSelectElement.prototype, "value").set.call(node, "SYN-1");
    node.dispatchEvent(new dom.window.Event("change", { bubbles: true }));
  });
}
test("source review, actual code evaluation and adoption require three explicit confirmations", async () => {
  const f = await render(); await choose();
  assert.equal(container.querySelectorAll("script").length, 0);
  assert.equal(button("원문·규칙 연결 확인").disabled, true);
  assert.equal(button("준비한 코드 사례 실행").disabled, true);
  await click(container.querySelector('[aria-label="출처와 범위 직접 확인"]'));
  await click(button("원문·규칙 연결 확인"));
  assert.equal(button("이 지원서에 적용 승인").disabled, true);
  await click(container.querySelector('[aria-label="출처와 범위 직접 확인"]'));
  await click(button("준비한 코드 사례 실행"));
  assert.equal(f.calls.length, 2);
  assert.equal(button("이 지원서에 적용 승인").disabled, true);
  await click(container.querySelector('[aria-label="출처와 범위 직접 확인"]'));
  await click(button("이 지원서에 적용 승인"));
  assert.deepEqual(f.calls.map(c => c.url.split("/").at(-1)), ["source-review", "evaluate", "activate"]);
  assert.equal(f.calls[2].body.rule_id, "SYN-1");
  for (const call of f.calls) for (const forbidden of ["status", "approved", "owner_id", "source_file", "excerpt", "verdict"]) assert.equal(forbidden in call.body, false);
});
test("unapproved or missing source remains inactive even after the confirmation checkbox", async () => {
  const state = fixture(); state.rules[0].candidate_52 = true; state.rules[0].proof = null; state.rules[0].excerpt = null;
  state.rules[0].issue = "미승인 후보는 활성화할 수 없습니다.";
  const f = await render(state); await choose();
  await click(container.querySelector('[aria-label="출처와 범위 직접 확인"]'));
  assert.equal(button("원문·규칙 연결 확인").disabled, true);
  assert.equal(button("이 지원서에 적용 승인").disabled, true);
  assert.equal(f.calls.length, 0);
});
test("conflict does not auto-retry or invent review proof", async () => {
  const state = fixture(); let writes = 0;
  await render(state, async (url, body) => { if (!body) return state; writes++; throw new Error("버전 충돌409"); });
  await choose(); await click(container.querySelector('[aria-label="출처와 범위 직접 확인"]'));
  await click(button("원문·규칙 연결 확인"));
  assert.equal(writes, 1); assert.match(container.querySelector('[role="alert"]').textContent, /409/);
  assert.equal(button("준비한 코드 사례 실행").disabled, true);
});
test("retirement uses the adopted version when the contract has already changed", async () => {
  const state = fixture(); state.rules[0].contract.version = 2;
  state.rules[0].states.RuleActivation = { id: "old", current: false, data: { activation: "ACTIVE_SCOPED", rule_version: 1 } };
  const f = await render(state); await choose(); await click(container.querySelector('[aria-label="출처와 범위 직접 확인"]'));
  await click(button("규칙 사용 중단"));
  assert.equal(f.calls[0].body.rule_version, 1); assert.equal(f.calls[0].body.rule_id, "SYN-1");
});
test("disabled pilot does not display a missing-resource error in the normal workspace", async () => {
  await render(fixture(), async () => { const error = new Error("not found"); error.status = 404; throw error; });
  assert.equal(container.textContent, "");
});
