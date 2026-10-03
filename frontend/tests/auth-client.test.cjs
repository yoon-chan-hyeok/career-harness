/* eslint-disable @typescript-eslint/no-require-imports */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

function client(fetcher, saved) {
  const values = new Map(
    saved ? [["career-supabase-session", JSON.stringify(saved)]] : [],
  );
  const storage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
  };
  const context = {
    exports: {},
    URL,
    Date,
    Number,
    JSON,
    Boolean,
    Error,
    AbortSignal,
    window: {},
    sessionStorage: storage,
    fetch: fetcher,
  };
  const source = fs.readFileSync(
    path.join(__dirname, "../app/auth-client.ts"),
    "utf8",
  );
  vm.runInNewContext(
    ts.transpileModule(source, {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
      },
    }).outputText,
    context,
  );
  const api = context.exports;
  api.configureAuth({
    provider: "supabase",
    supabase_url: "https://example.supabase.co",
    publishable_key: "sb_publishable_fixture",
  });
  return { api, values };
}
const response = (access = "access", refresh = "refresh", lifetime = 3600) => ({
  ok: true,
  json: async () => ({
    access_token: access,
    refresh_token: refresh,
    expires_in: lifetime,
  }),
});

test("password grant sends only public key and token refresh rotates once across concurrent requests", async () => {
  const calls = [];
  const { api } = client(async (url, options) => {
    calls.push({ url, options });
    return response(
      calls.length === 1 ? "old-access" : "new-access",
      "rotated-refresh",
      calls.length === 1 ? 1 : 3600,
    );
  });
  await api.signIn("fixture@example.com", "fixture-password");
  assert.deepEqual(await Promise.all([api.accessToken(), api.accessToken()]), [
    "new-access",
    "new-access",
  ]);
  assert.equal(calls.length, 2);
  assert.ok(calls[0].url.endsWith("/token?grant_type=password"));
  assert.equal(calls[0].options.headers.apikey, "sb_publishable_fixture");
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    refresh_token: "rotated-refresh",
  });
});

test("restored session remains isolated to its project and malformed configuration cannot redirect credentials", async () => {
  const saved = {
    access_token: "saved-access",
    refresh_token: "saved-refresh",
    project: "https://example.supabase.co",
    expires_at: Date.now() / 1000 + 3600,
  };
  const { api } = client(async () => {
    throw Error("no network expected");
  }, saved);
  assert.equal(await api.accessToken(), "saved-access");
  assert.throws(() =>
    api.configureAuth({
      provider: "supabase",
      supabase_url: "https://example.supabase.co/redirect",
      publishable_key: "fixture",
    }),
  );
  api.configureAuth({
    provider: "supabase",
    supabase_url: "https://other.supabase.co",
    publishable_key: "fixture",
  });
  assert.equal(api.hasSession(), false);
});

test("failed refresh removes private credentials; failed account switch cannot reuse old account", async () => {
  let count = 0;
  const { api, values } = client(async () =>
    ++count === 1 ? response("old", "refresh", 1) : { ok: false },
  );
  await api.signIn("old@example.com", "password");
  await assert.rejects(api.accessToken());
  assert.equal(api.hasSession(), false);
  assert.equal(values.size, 0);
  await assert.rejects(api.signIn("new@example.com", "bad"));
  await assert.rejects(api.accessToken());
});

test("logout revokes local session immediately and late refresh cannot restore it", async () => {
  let complete;
  let count = 0;
  const { api, values } = client(async (url) => {
    if (url.includes("logout")) return { ok: true };
    if (++count === 1) return response("old", "refresh", 1);
    return new Promise((resolve) => {
      complete = resolve;
    });
  });
  await api.signIn("fixture@example.com", "password");
  const pending = api.accessToken();
  await api.signOut();
  assert.equal(api.hasSession(), false);
  complete(response("late-access"));
  await assert.rejects(pending);
  assert.equal(values.size, 0);
});
