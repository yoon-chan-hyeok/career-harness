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
