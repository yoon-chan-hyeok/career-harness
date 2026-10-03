/* eslint-disable @typescript-eslint/no-require-imports */
const test = require("node:test");
const assert = require("node:assert/strict");
const { spawnSync } = require("node:child_process");
const path = require("node:path");

function load(extra) {
  const env = { ...process.env, ...extra };
  if (extra.BACKEND_URL === undefined) delete env.BACKEND_URL;
  return spawnSync(process.execPath, ["--input-type=module", "-e",
    "import config from './next.config.mjs'; console.log(JSON.stringify(await config.rewrites()));"],
    { cwd: path.join(__dirname, ".."), env, encoding: "utf8" });
}

test("local standalone build retains the loopback development backend", () => {
  const result = load({ VERCEL: "0", BACKEND_URL: undefined });
  assert.equal(result.status, 0);
  assert.equal(JSON.parse(result.stdout)[0].destination, "http://127.0.0.1:8000/api/:path*");
});

test("Vercel requires a backend before frontend deployment", () => {
  const result = load({ VERCEL: "1", BACKEND_URL: undefined });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /explicit HTTPS origin/);
});

test("unsafe Vercel targets fail without leaking credentials into build errors", () => {
  for (const url of [
    "http://backend.example", "https://backend.example/api", "https://backend.example/?q=secret_fixture",
    "https://backend.example/#secret_fixture", "https://user:secret_fixture@backend.example/",
  ]) {
    const result = load({ VERCEL: "1", BACKEND_URL: url });
    assert.notEqual(result.status, 0, url);
    assert.match(result.stderr, /explicit HTTPS origin/);
    assert.doesNotMatch(result.stderr, /secret_fixture|user:/);
  }
});

test("Vercel HTTPS origin produces a same-origin API proxy without a double slash", () => {
  const result = load({ VERCEL: "1", BACKEND_URL: "https://career-backend.example/" });
  assert.equal(result.status, 0);
  assert.deepEqual(JSON.parse(result.stdout), [{
    source: "/api/:path*", destination: "https://career-backend.example/api/:path*",
  }]);
});
