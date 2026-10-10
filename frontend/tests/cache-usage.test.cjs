/* eslint-disable @typescript-eslint/no-require-imports */
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const ts = require("typescript");

const context = { exports: {} };
vm.runInNewContext(
  ts.transpileModule(
    fs.readFileSync(
      path.join(__dirname, "../app/cache-usage-format.ts"),
      "utf8",
    ),
    { compilerOptions: { module: ts.ModuleKind.CommonJS } },
  ).outputText,
  context,
);
const { formatCacheUsage } = context.exports;
const report = (values = {}) => ({
  generative_calls: 5,
  reported_calls: 3,
  unknown_calls: 1,
  invalid_calls: 1,
  hit_calls: 1,
  input_tokens: 1000,
  cached_tokens: 400,
  hit_ratio: 0.4,
  ...values,
});

test("reuse ratio describes observed tokens rather than the fraction of calls with a hit", () => {
  const display = formatCacheUsage(report());
  assert.equal(display.status, "40%");
  assert.equal(display.tokens, "재사용 400 / 관측된 입력 1,000 토큰");
  assert.equal(display.coverage, "관측된 3회 / 전체 작성 요청 5회");
  assert.equal(display.unreported, "미확인 1회 · 잘못된 수치 1회");
});

test("missing reports never imply zero reuse and retain unknown or invalid coverage", () => {
  const display = formatCacheUsage(
    report({
      reported_calls: 0,
      unknown_calls: 4,
      invalid_calls: 1,
      input_tokens: 0,
      cached_tokens: 0,
      hit_ratio: 0,
    }),
  );
  assert.equal(display.status, "미확인");
  assert.equal(display.tokens, null);
  assert.equal(display.coverage, "관측된 0회 / 전체 작성 요청 5회");
  assert.equal(display.unreported, "미확인 4회 · 잘못된 수치 1회");
});

test("an observed zero is distinct from absent legacy data and an empty writing history", () => {
  assert.equal(
    formatCacheUsage(report({ cached_tokens: 0, hit_ratio: 0 })).status,
    "0%",
  );
  assert.equal(formatCacheUsage().status, "미확인");
  assert.equal(formatCacheUsage(null).tokens, null);
  const empty = formatCacheUsage(
    report({ generative_calls: 0, reported_calls: 0 }),
  );
  assert.equal(empty.status, "아직 작성 기록 없음");
  assert.equal(empty.coverage, null);
});

test("unusable totals and absent ratios do not produce an apparent measured percentage", () => {
  for (const values of [
    { input_tokens: null },
    { cached_tokens: null },
    { cached_tokens: -1 },
    { input_tokens: 100, cached_tokens: 200 },
    { input_tokens: 0, cached_tokens: 0, hit_ratio: 0 },
    { hit_ratio: null },
    { hit_ratio: NaN },
    { hit_ratio: Infinity },
    { hit_ratio: -0.5 },
    { hit_ratio: 2 },
  ]) {
    assert.equal(formatCacheUsage(report(values)).status, "미확인");
  }
});

test("small positive reuse does not round down to zero and large token totals remain readable", () => {
  const display = formatCacheUsage(
    report({
      input_tokens: 1234567890,
      cached_tokens: 100,
      hit_ratio: 100 / 1234567890,
    }),
  );
  assert.equal(display.status, "0.1% 미만");
  assert.equal(display.tokens, "재사용 100 / 관측된 입력 1,234,567,890 토큰");
});
