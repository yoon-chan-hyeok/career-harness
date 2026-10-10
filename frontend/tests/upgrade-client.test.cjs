/* eslint-disable @typescript-eslint/no-require-imports */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");
const { webcrypto } = require("node:crypto");
function moduleApi(file, fetcher) {
  const context = {
    exports: {},
    fetch: fetcher,
    Response,
    FormData,
    AbortController,
    crypto: webcrypto,
    TextEncoder,
    Uint8Array,
    Map,
    Set,
    Error,
    TypeError,
    JSON,
    Array,
    String,
    Object,
    Number,
    URL,
    setTimeout,
    clearTimeout,
  };
  vm.runInNewContext(
    ts.transpileModule(
      fs.readFileSync(path.join(__dirname, "../app", file), "utf8"),
      {
        compilerOptions: {
          module: ts.ModuleKind.CommonJS,
          target: ts.ScriptTarget.ES2022,
        },
      },
    ).outputText,
    context,
  );
  return context.exports;
}
test("HTML 401 resets authentication before error parsing, without exposing upstream content", async () => {
  let reset = 0;
  const { createApiClient } = moduleApi(
    "api-client.ts",
    async () =>
      new Response("<html>secret_provider_token</html>", { status: 401 }),
  );
  const api = createApiClient(
    async () => "fixture",
    () => reset++,
  );
  await assert.rejects(api.request("/private"), /로그인이 만료/);
  assert.equal(reset, 1);
});
test("same uncertain mutation preserves key on user retry, changed body gets a new key, success clears it", async () => {
  const calls = [];
  let failing = true;
  const { createApiClient } = moduleApi(
    "api-client.ts",
    async (url, options) => {
      calls.push(options.headers["Idempotency-Key"]);
      return new Response(failing ? "provider_secret" : '{"ok":true}', {
        status: failing ? 503 : 200,
      });
    },
  );
  const api = createApiClient(
    async () => "fixture",
    () => {},
  );
  await assert.rejects(
    api.request("/actions/generate", { text: "first" }),
    /서비스가 잠시/,
  );
  await assert.rejects(api.request("/actions/generate", { text: "first" }));
  assert.equal(calls[0], calls[1]);
  await assert.rejects(api.request("/actions/generate", { text: "changed" }));
  assert.notEqual(calls[1], calls[2]);
  failing = false;
  await api.request("/actions/generate", { text: "first" });
  await api.request("/actions/generate", { text: "first" });
  assert.equal(calls[3], calls[0]);
  assert.notEqual(calls[4], calls[3]);
});
test("deadline and network failures are readable and do not automatically repeat model work", async () => {
  let calls = 0;
  const { createApiClient } = moduleApi(
    "api-client.ts",
    async (_url, options) => {
      calls++;
      return new Promise((_, reject) =>
        options.signal.addEventListener("abort", () =>
          reject(new Error("aborted")),
        ),
      );
    },
  );
  const api = createApiClient(
    async () => "fixture",
    () => {},
    5,
  );
  await assert.rejects(api.request("/work", {}), /실행 기록/);
  assert.equal(calls, 1);
  const second = moduleApi("api-client.ts", async () => {
    throw new TypeError("offline");
  }).createApiClient(
    async () => "fixture",
    () => {},
  );
  await assert.rejects(second.request("/work"), /네트워크 연결/);
});
test("payment and throttling HTML errors give distinct instructions", async () => {
  for (const [status, pattern] of [
    [402, /무료 사용 한도/],
    [429, /사용 한도에 도달/],
  ]) {
    const api = moduleApi(
      "api-client.ts",
      async () => new Response("secret", { status }),
    ).createApiClient(
      async () => "fixture",
      () => {},
    );
    await assert.rejects(api.request("/work"), pattern);
  }
});
test("draft serializer excludes credentials and approvals while retaining actual editable fields", () => {
  const { serializeDraftFields } = moduleApi("draft-fields.ts");
  const field = (type, name, value) => ({ type, name, id: "", value });
  const result = serializeDraftFields([
    field("textarea", "text", "my draft"),
    field("checkbox", "confirmed", "on"),
    field("password", "password", "secret"),
    field("text", "api_key", "secret"),
    field("text", "approval", "true"),
    field("hidden", "token", "secret"),
    field("file", "source", "private.pdf"),
    field("select-one", "pages", "2"),
  ]);
  assert.deepEqual(JSON.parse(JSON.stringify(result)), {
    "0:text": { value: "my draft", kind: "textarea" },
    "1:pages": { value: "2", kind: "select-one" },
  });
});

test("late-loaded review fields are clean while real edits in other forms stay protected after saving", () => {
  const { draftHasChanges } = moduleApi("draft-fields.ts");
  const field = (value) => ({ value, kind: "textarea" });
  const initial = { "0:essay": field("saved essay") };
  const defaults = {
    "0:essay": field("saved essay"),
    "1:proof": field("source quote"),
    "2:answer": field(""),
  };
  assert.equal(draftHasChanges(defaults, initial, defaults), false);
  const edited = { ...defaults, "2:answer": field("my answer") };
  assert.equal(draftHasChanges(edited, initial, defaults), true);
  const afterSave = { ...initial, "2:answer": field("my answer") };
  assert.equal(draftHasChanges(edited, afterSave, defaults), false);
  assert.equal(
    draftHasChanges(
      { ...edited, "0:essay": field("unsaved essay") },
      afterSave,
      defaults,
    ),
    true,
  );
  assert.equal(
    draftHasChanges(
      { ...edited, "1:proof": field("changed proof") },
      afterSave,
      defaults,
    ),
    true,
  );
});

test("resume budget label preserves version goals and does not invent missing page counts", () => {
  const { resumeBudgetLabel } = moduleApi("resume-budget.ts");
  assert.equal(resumeBudgetLabel({ page_budget: 2 }), "2페이지");
  assert.equal(
    resumeBudgetLabel({ page_budget: "MASTER" }),
    "전체 경력 마스터",
  );
  assert.equal(resumeBudgetLabel({ character_budget: 7000 }), "2페이지");
  assert.equal(resumeBudgetLabel({}), "미기록");
  assert.equal(
    resumeBudgetLabel({ page_budget: 0, character_budget: 5000 }),
    "미기록",
  );
});

test("an in-progress conflict does not discard the original retry key", async () => {
  const keys = [];
  const api = moduleApi("api-client.ts", async (_url, options) => {
    keys.push(options.headers["Idempotency-Key"]);
    return new Response('{"detail":"진행 중인 작업을 확인해 주세요."}', {
      status: 409,
    });
  }).createApiClient(
    async () => "fixture",
    () => {},
  );
  await assert.rejects(api.request("/actions/generate", { text: "same" }));
  await assert.rejects(api.request("/actions/generate", { text: "same" }));
  assert.equal(keys[0], keys[1]);
});

test("source links reject credentials, redirects, queries and unconfigured destinations", () => {
  const { safeRepositoryUrl } = moduleApi("workroom-state.ts");
  assert.equal(
    safeRepositoryUrl("https://github.com/example/career-harness/"),
    "https://github.com/example/career-harness",
  );
  for (const value of [
    undefined,
    "",
    "javascript:alert(1)",
    "https://github.com.evil.test/user/repo",
    "https://secret@github.com/user/repo",
    "https://github.com/user/repo?token=secret",
    "https://github.com/user/repo#secret",
    "http://github.com/user/repo",
    "https://github.com:444/user/repo",
    "https://github.com/user/repo/blob/main/private.md",
  ]) {
    assert.equal(safeRepositoryUrl(value), null);
  }
});

test("agent messages require an actual artifact, execution or trace and preserve server wording", () => {
  const { recordedMessages } = moduleApi("workroom-state.ts");
  const role = (key, message, extra = {}) => ({
    key,
    label: key,
    status: "DONE",
    message,
    basis: "saved",
    artifact_id: null,
    execution_run_id: null,
    trace_id: null,
    updated_at: "2026-10-04T10:00:00Z",
    ...extra,
  });
  const records = [
    role("research", "Invented dialogue without a record"),
    role("writing", "", { artifact_id: "doc-1" }),
    role("evidence", "Stored evidence result", { artifact_id: "doc-2" }),
    role("review", "Failed actual execution", {
      execution_run_id: "run-1",
      status: "FAILED",
      updated_at: "2026-10-04T11:00:00Z",
    }),
    role("strategy", "Verified model trace", {
      trace_id: "trace-1",
      updated_at: "2026-10-04T09:00:00Z",
    }),
  ];
  const result = recordedMessages(records);
  assert.deepEqual(
    Array.from(result, (item) => item.key),
    ["review", "evidence", "strategy"],
  );
  assert.equal(result[0].message, "Failed actual execution");
  assert.equal(records[0].key, "research");
  assert.equal(recordedMessages([]).length, 0);
});
