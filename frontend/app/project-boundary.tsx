"use client";

import { FormEvent, useEffect, useState } from "react";

type Rule = {
  id: string;
  title: string;
  section: string;
  start_line: number;
  end_line: number;
  text: string;
  checks: { code: string; label: string; source_quote: string }[];
};
type Context = {
  evidence_hash: string;
  rules: Rule[];
  suggested_rule_id: string;
  needs_review: boolean;
  binding: { rule_id: string; title: string | null; version: number } | null;
};

export function ProjectBoundary({
  evidence,
  request,
  refresh,
}: {
  evidence: { id: string; title: string; body: string; status: string };
  request: <T>(path: string, body?: object, method?: string) => Promise<T>;
  refresh: () => Promise<unknown>;
}) {
  const [open, setOpen] = useState(false);
  const [context, setContext] = useState<Context | null>(null);
  const [selected, setSelected] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [revision, setRevision] = useState(0);
  const path = `/evidence/${evidence.id}/project-boundary`;
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoading(true);
    setContext(null);
    setConfirmed(false);
    setError("");
    request<Context>(path)
      .then((value) => {
        if (cancelled) return;
        setContext(value);
        setSelected(
          value.binding ? value.binding.rule_id : value.suggested_rule_id,
        );
      })
      .catch((reason) => {
        if (!cancelled)
          setError(
            reason instanceof Error
              ? reason.message
              : "프로젝트 규칙을 불러오지 못했습니다.",
          );
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    open,
    path,
    request,
    evidence.title,
    evidence.body,
    evidence.status,
    revision,
  ]);
  const rule = context?.rules.find((item) => item.id === selected);
  const valid = context && (!selected || rule);
  const eligible = ["VERIFIED", "USER_CONFIRMED", "SOURCE_BACKED"].includes(
    evidence.status,
  );
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!context || !valid || !eligible || !confirmed || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await request<{ stale_artifacts: string[] }>(path, {
        rule_id: selected,
        evidence_hash: context.evidence_hash,
        confirmed: true,
      });
      setConfirmed(false);
      setMessage(
        result.stale_artifacts.length
          ? "연결을 저장했습니다. 이 경험을 사용한 기존 결과는 다시 검토해 주세요."
          : "이 경험에 적용할 프로젝트 규칙을 저장했습니다.",
      );
      setRevision((value) => value + 1);
      await refresh();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "연결을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <details
      className="project-boundary"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>프로젝트 표현 제한</summary>
      {loading && (
        <p role="status">현재 경험과 작성 규칙을 불러오고 있습니다.</p>
      )}
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {context && (
        <>
          <p>
            작성전략의 프로젝트 규칙을 이 경험에 연결하세요. 규칙의 예시나
            수치는 개인 사실로 등록하지 않습니다.
          </p>
          {context.needs_review && (
            <p role="status">
              {context.binding
                ? "경험이나 규칙이 바뀌었습니다. 아래 원문과 적용 여부를 다시 확인해 주세요."
                : "같은 이름의 프로젝트 규칙이 있습니다. 원문을 읽고 적용 여부를 직접 확인해 주세요."}
            </p>
          )}
          {!context.rules.length && (
            <p>
              현재 활성 작성전략에 프로젝트별 규칙이 없습니다. 설정에서
              작성전략을 등록할 수 있습니다.
            </p>
          )}
          {context.binding && (
            <p>
              마지막 확인: {context.binding.title || "적용할 규칙 없음"} ·{" "}
              {context.binding.version}차
            </p>
          )}
          <form onSubmit={submit}>
            <fieldset disabled={busy || loading}>
              <label htmlFor={`project-rule-${evidence.id}`}>
                적용할 프로젝트 규칙
              </label>
              <select
                id={`project-rule-${evidence.id}`}
                value={selected}
                onChange={(event) => {
                  setSelected(event.target.value);
                  setConfirmed(false);
                  setMessage("");
                }}
              >
                <option value="">
                  연결하지 않음 — 이 경험에 적용할 규칙이 없음
                </option>
                {selected && !rule && (
                  <option value={selected} disabled>
                    이전 규칙 — 현재 원문에서 다시 선택해 주세요
                  </option>
                )}
                {context.rules.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.title}
                  </option>
                ))}
              </select>
              {rule && (
                <div>
                  <p>
                    {rule.section} · 원문 {rule.start_line}–{rule.end_line}행
                  </p>
                  <p className="evidence-body">{rule.text}</p>
                  {!!rule.checks.length && (
                    <ul>
                      {rule.checks.map((check) => (
                        <li key={check.code}>{check.label}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
              <label className="check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                이 경험과 규칙 원문을 직접 대조하고 적용 여부를 확인했습니다.
              </label>
              {!eligible && (
                <p>
                  경험의 원자료와 수행 범위를 확인한 뒤 규칙을 연결할 수
                  있습니다.
                </p>
              )}
              <button disabled={!eligible || !confirmed || !valid || busy}>
                프로젝트 규칙 연결 저장
              </button>
            </fieldset>
          </form>
        </>
      )}
    </details>
  );
}
