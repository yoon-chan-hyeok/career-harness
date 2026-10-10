import { formatCacheUsage, type CacheUsageReport } from "./cache-usage-format";

export function CacheUsage({ cache }: { cache?: CacheUsageReport | null }) {
  const display = formatCacheUsage(cache);
  return (
    <div style={{ marginTop: 10, minWidth: 0, overflowWrap: "anywhere" }}>
      <small>입력 재사용 · {display.status}</small>
      {display.tokens ? <small>{display.tokens}</small> : null}
      {display.coverage ? <small>{display.coverage}</small> : null}
      {display.unreported ? <small>{display.unreported}</small> : null}
    </div>
  );
}
