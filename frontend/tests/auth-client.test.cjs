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

test("guest trial uses its own session, resumes without email calls, and clears on mode change", async () => {
  const calls = [];
  const { api } = client(async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      json: async () => ({
        access_token: "guest-fixture",
        expires_in: 86400,
        token_type: "bearer",
      }),
    };
  });
  api.configureAuth({ provider: "guest" });
  await api.startGuest();
  assert.equal(await api.accessToken(), "guest-fixture");
  api.configureAuth({ provider: "guest" });
  assert.equal(await api.accessToken(), "guest-fixture");
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/auth/guest");
  assert.equal(calls[0].options.cache, "no-store");
  api.configureAuth({
    provider: "supabase",
    supabase_url: "https://example.supabase.co",
    publishable_key: "sb_publishable_fixture",
  });
  await assert.rejects(api.accessToken());
});

test("guest creation cannot restore a session after logout or accept an overlong lifetime", async () => {
  let finish;
  const { api } = client(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  api.configureAuth({ provider: "guest" });
  const pending = api.startGuest();
  api.clearSession();
  finish({
    ok: true,
    json: async () => ({
      access_token: "discarded",
      expires_in: 86400,
      token_type: "bearer",
    }),
  });
  await assert.rejects(pending);
  assert.equal(api.hasSession(), false);
  const second = client(async () => ({
    ok: true,
    json: async () => ({
      access_token: "bad",
      expires_in: 86401,
      token_type: "bearer",
    }),
  }));
  second.api.configureAuth({ provider: "guest" });
  await assert.rejects(second.api.startGuest());
  assert.equal(second.api.hasSession(), false);
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

const otpResponse = (
  access = "otp-access",
  email = "fixture@example.test",
) => ({
  ok: true,
  json: async () => ({
    access_token: access,
    refresh_token: "otp-refresh",
    expires_in: 3600,
    user: {
      email,
      email_confirmed_at: "2026-10-05T00:00:00Z",
      is_anonymous: false,
    },
  }),
});

test("public OTP uses fixed project, captcha, explicit signup and email verification", async () => {
  const calls = [];
  const { api, values } = client(async (url, options) => {
    calls.push({ url, options });
    return url.endsWith("/verify") ? otpResponse() : { ok: true };
  });
  await assert.rejects(api.requestEmailCode("fixture@example.test", ""));
  assert.equal(calls.length, 0);
  const challenge = await api.requestEmailCode(
    "fixture@example.test",
    "synthetic-captcha",
    { createUser: true },
  );
  assert.equal(api.hasSession(), false);
  assert.equal(calls[0].url, "https://example.supabase.co/auth/v1/otp");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    email: "fixture@example.test",
    create_user: true,
    gotrue_meta_security: { captcha_token: "synthetic-captcha" },
  });
  assert.equal(calls[0].options.redirect, "error");
  await api.verifyEmailCode("fixture@example.test", "123456", challenge);
  assert.deepEqual(JSON.parse(calls[1].options.body), {
    email: "fixture@example.test",
    token: "123456",
    type: "email",
  });
  assert.equal(await api.accessToken(), "otp-access");
  assert.equal(values.size, 1);
});

test("cancelled or wrong-account OTP cannot install a session", async () => {
  let finish;
  const { api } = client(async (url) =>
    url.endsWith("/verify")
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : { ok: true },
  );
  const challenge = await api.requestEmailCode(
    "fixture@example.test",
    "captcha",
  );
  const pending = api.verifyEmailCode(
    "fixture@example.test",
    "123456",
    challenge,
  );
  api.clearSession();
  finish(otpResponse());
  await assert.rejects(pending);
  assert.equal(api.hasSession(), false);
  const second = await api.requestEmailCode("fixture@example.test", "captcha");
  const wrong = api.verifyEmailCode("fixture@example.test", "123456", second);
  finish(otpResponse("wrong", "someone-else@example.test"));
  await assert.rejects(wrong);
  assert.equal(api.hasSession(), false);
});

test("deletion reauthentication does not replace current account and never creates a new user", async () => {
  const calls = [];
  const { api } = client(
    async (url, options) => {
      calls.push(JSON.parse(options.body));
      return url.endsWith("/verify")
        ? otpResponse("fresh-proof")
        : { ok: true };
    },
    {
      access_token: "existing-owner",
      refresh_token: "existing-refresh",
      project: "https://example.supabase.co",
      expires_at: Date.now() / 1000 + 3600,
    },
  );
  const challenge = await api.requestEmailCode(
    "fixture@example.test",
    "captcha",
    { createUser: false, reauthentication: true },
  );
  assert.equal(calls[0].create_user, false);
  assert.equal(
    await api.verifyEmailCode(
      "fixture@example.test",
      "123456",
      challenge,
      false,
    ),
    "fresh-proof",
  );
  assert.equal(await api.accessToken(), "existing-owner");
});
