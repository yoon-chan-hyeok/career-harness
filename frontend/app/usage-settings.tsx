"use client";
import { FormEvent, useCallback, useEffect, useState } from "react";
import type { Request } from "./api-client";
import { CacheUsage } from "./cache-usage";
import { inputReuseNotice, type CacheUsageReport } from "./cache-usage-format";

type Limits = {
  daily_calls: number;
  monthly_calls: number;
  daily_tokens: number;
  monthly_tokens: number;
  daily_cost_usd: number | null;
  monthly_cost_usd: number | null;
};
type Totals = {
  calls: number;
  tokens: number;
  estimated_cost_usd: number | null;
  unknown_cost_calls: number;
  reserved_calls: number;
  reserved_tokens: number;
  remaining_calls: number;
  remaining_tokens: number;
  cache?: CacheUsageReport | null;
};
type Usage = {
  managed?: boolean;
  daily: Totals;
  monthly: Totals;
  limits?: Limits;
  timezone: string;
  notice?: string;
};

export function UsageSettings({ request }: { request: Request }) {
  const [usage, setUsage] = useState<Usage | null>(null);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const load = useCallback(async () => {
    const [data, configured] = await Promise.all([
      request("/usage"),
      request("/usage/limits"),
    ]);
    setUsage(data);
    setLimits(configured.limits);
  }, [request]);
  useEffect(() => {
    let active = true;
    load().catch(() => {
      if (active)
        setMessage(
          "사용량을 불러오지 못했습니다. 다시 불러오기를 눌러 주세요.",
        );
    });
    return () => {
      active = false;
    };
  }, [load]);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = Object.fromEntries(
      Object.keys(limits || {}).map((key) => [
        key,
        data.get(key) === "" ? null : Number(data.get(key)),
      ]),
    );
    setBusy(true);
    setMessage("");
    try {
      await request("/usage/limits", value, "PUT");
      await load();
      setMessage("내 사용 상한을 저장했습니다.");
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "상한을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="usage-settings">
      <h3>AI 사용량과 실행 상한</h3>
      {usage?.managed && (
        <p className="muted">
          운영자가 정한 상한 안에서 더 낮은 개인 한도를 설정할 수 있습니다.
          서비스 전체 공용 한도도 함께 적용됩니다.
        </p>
      )}
      <p className="muted">
        사용 한도는 내 계정의 호출을 제한합니다. 제공자 무료 크레딧 잔액은
        제공자 계정에서 확인하세요. 계산할 수 없는 비용은 0원으로 표시하지
        않습니다.
      </p>
      {usage && (
        <>
          <div className="usage-totals">
            {(
              [
                ["오늘", usage.daily],
                ["이번 달", usage.monthly],
              ] as const
            ).map(([label, total]) => (
              <div key={label}>
                <strong>
                  {label} · {usage.timezone} 기준
                </strong>
                <p>
                  사용·예약 합계 {Number(total?.calls || 0).toLocaleString()}회
                </p>
                <small>
                  사용·예약 합계 {Number(total?.tokens || 0).toLocaleString()}{" "}
                  토큰
                </small>
                <small>
                  예약 {Number(total?.reserved_calls || 0).toLocaleString()}회 ·{" "}
                  {Number(total?.reserved_tokens || 0).toLocaleString()} 토큰
                </small>
                <small>
                  남은 상한{" "}
                  {Number(total?.remaining_calls || 0).toLocaleString()}회 ·{" "}
                  {Number(total?.remaining_tokens || 0).toLocaleString()} 토큰
                </small>
                <small>
                  추정 비용{" "}
                  {typeof total?.estimated_cost_usd === "number"
                    ? `$${total.estimated_cost_usd.toFixed(4)}`
                    : `미확인${total?.unknown_cost_calls ? ` · 미확인 호출 ${total.unknown_cost_calls}회` : ""}`}
                </small>
                <CacheUsage cache={total?.cache} />
              </div>
            ))}
          </div>
          <p className="muted">{inputReuseNotice}</p>
          {usage.notice && <p className="muted">{usage.notice}</p>}
        </>
      )}
      <button
        className="secondary"
        disabled={busy}
        onClick={() =>
          void load()
            .then(() => setMessage(""))
            .catch(() => setMessage("사용량을 불러오지 못했습니다."))
        }
      >
        사용량 다시 불러오기
      </button>
      {limits && (
        <form
          key={JSON.stringify(limits)}
          onSubmit={(event) => void save(event)}
        >
          <div className="grid">
            {Object.entries({
              daily_calls: "하루 호출 상한",
              monthly_calls: "월 호출 상한",
              daily_tokens: "하루 토큰 상한",
              monthly_tokens: "월 토큰 상한",
              daily_cost_usd: "하루 비용 상한 (USD)",
              monthly_cost_usd: "월 비용 상한 (USD)",
            }).map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  name={key}
                  type="number"
                  min="0"
                  step={key.endsWith("usd") ? "0.001" : "1"}
                  required={!key.endsWith("usd")}
                  defaultValue={limits[key as keyof Limits] ?? ""}
                />
              </label>
            ))}
          </div>
          <p className="muted">
            비용 상한을 사용하면 비용이 확인되지 않은 호출도 제한될 수 있습니다.
            숫자 0은 실행을 막는 상한입니다.
          </p>
          <button disabled={busy}>
            {busy ? "저장 중…" : "사용 상한 저장"}
          </button>
        </form>
      )}
      {message && (
        <p role="status" className="note">
          {message}
        </p>
      )}
    </section>
  );
}
