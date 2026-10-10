export type CacheUsageReport = {
  generative_calls: number;
  reported_calls: number;
  unknown_calls: number;
  invalid_calls: number;
  hit_calls: number;
  input_tokens: number | null;
  cached_tokens: number | null;
  hit_ratio: number | null;
};

export const inputReuseNotice =
  "입력 재사용은 AI 제공자가 관리하며 이전 입력의 계산만 다시 활용하고, 글은 요청할 때마다 새로 생성됩니다.";

function validCount(value: number | null): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function countLabel(value: number) {
  return validCount(value) ? value.toLocaleString("ko-KR") : "미확인";
}

export function formatCacheUsage(cache?: CacheUsageReport | null) {
  if (!cache) {
    return {
      status: "미확인",
      tokens: null,
      coverage: null,
      unreported: "입력 재사용 수치를 아직 확인하지 못했습니다.",
    };
  }
  if (cache.generative_calls === 0) {
    return {
      status: "아직 작성 기록 없음",
      tokens: null,
      coverage: null,
      unreported: null,
    };
  }
  const inputTokens = cache.input_tokens;
  const cachedTokens = cache.cached_tokens;
  const hasReportedTokens =
    cache.reported_calls > 0 &&
    validCount(inputTokens) &&
    validCount(cachedTokens) &&
    cachedTokens <= inputTokens;
  const ratio = cache.hit_ratio;
  const hasRatio =
    hasReportedTokens &&
    (inputTokens ?? 0) > 0 &&
    typeof ratio === "number" &&
    Number.isFinite(ratio) &&
    ratio >= 0 &&
    ratio <= 1;
  return {
    status: hasRatio
      ? ratio > 0 && ratio < 0.001
        ? "0.1% 미만"
        : `${(ratio * 100).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}%`
      : "미확인",
    tokens: hasReportedTokens
      ? `재사용 ${cachedTokens.toLocaleString("ko-KR")} / 관측된 입력 ${inputTokens.toLocaleString("ko-KR")} 토큰`
      : null,
    coverage: `관측된 ${countLabel(cache.reported_calls)}회 / 전체 작성 요청 ${countLabel(cache.generative_calls)}회`,
    unreported: `미확인 ${countLabel(cache.unknown_calls)}회 · 잘못된 수치 ${countLabel(cache.invalid_calls)}회`,
  };
}
