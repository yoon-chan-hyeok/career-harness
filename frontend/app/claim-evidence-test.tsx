"use client";

import { FormEvent, useContext, useEffect, useState } from "react";
import { EditorSaveContext } from "./editor-dialog";
import type { Artifact } from "./page";

type Data = Record<string, unknown>;
export type Evidence = { id: string; title: string; body: string; data: Data };
type Context = {
  brief_id: string;
  claims: string[];
  checks: Record<string, string>;
  evidence: Evidence[];
};
type Source = {
  key: string;
  evidenceId: string;
  recordId: string;
  title: string;
  text: string;
};

export function sources(evidence: Evidence[]): Source[] {
  return evidence.flatMap((e) => {
    const result = [
      {
        key: e.id,
        evidenceId: e.id,
        recordId: "",
        title: e.title,
        text: e.body,
      },
    ];
    for (const [field, label] of Object.entries({
      metric_ledger: "지표",
      confirmed_decision_episodes: "판단 기록",
      confirmed_ownership: "수행 범위",
      confirmed_claim_boundaries: "주장 범위",
    })) {
      for (const record of (e.data[field] || []) as Data[]) {
        if (
          !["VERIFIED", "USER_CONFIRMED", "SOURCE_BACKED"].includes(
            String(record.status),
          )
        )
          continue;
        const data = (record.data || record) as Data;
        const text = Object.entries(data)
          .filter(
            ([key]) =>
              !["id", "source_id", "evidence_id", "status", "version"].includes(
                key,
              ),
          )
          .flatMap(([, value]) =>
            typeof value === "string"
              ? [value]
              : Array.isArray(value)
                ? value.map(String)
                : [],
          )
          .filter(Boolean)
          .join("\n");
        result.push({
          key: String(record.id),
          evidenceId: e.id,
          recordId: String(record.id),
          title: `${e.title} · ${label}`,
          text,
        });
      }
    }
    return result;
  });
}

export function ClaimEvidencePanel({
  workspaceId,
  brief,
  result,
  ai,
  request,
  act,
}: {
  workspaceId: string;
  brief: Artifact;
  result?: Artifact;
  ai: boolean;
  request: <T>(path: string, body?: object, method?: string) => Promise<T>;
  act: (action: string, body: object) => Promise<unknown>;
}) {
  const [context, setContext] = useState<Context | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const editor = useContext(EditorSaveContext);
  useEffect(() => {
    let cancelled = false;
    request<Context>(
      `/applications/${workspaceId}/questions/${brief.slot}/evidence-test-context`,
    )
      .then((value) => {
        if (!cancelled) {
          setContext(value);
          setError("");
        }
      })
      .catch(() => {
        if (!cancelled) setError("현재 메시지와 원문을 불러오지 못했습니다.");
      });
    return () => {
      cancelled = true;
    };
  }, [request, workspaceId, brief.slot, brief.id, reload]);
  const run = async (body: object, saved?: () => void) => {
    setBusy(true);
    setError("");
    try {
      await act("claim-test", {
        qid: brief.slot,
        artifact_id: brief.id,
        ...body,
      });
      saved?.();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "검증 결과를 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  const sourceOptions = context ? sources(context.evidence) : [];
  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!context || context.brief_id !== brief.id) return;
    const form = new FormData(event.currentTarget);
    const claims = context.claims.map((claim, index) => {
      const source = sourceOptions.find(
        (item) => item.key === form.get(`source-${index}`),
      );
      const quote = String(form.get(`quote-${index}`) || "");
      return {
        claim,
        support: form.get(`support-${index}`),
        rationale: form.get(`reason-${index}`),
        citations:
          source && quote.trim()
            ? [
                {
                  evidence_id: source.evidenceId,
                  record_id: source.recordId,
                  quote,
                },
              ]
            : [],
      };
    });
    const checks = Object.keys(context.checks).map((key) => ({
      key,
      verdict: form.get(`verdict-${key}`),
      rationale: form.get(`reason-${key}`),
    }));
    const saved = editor.beginSave(event.currentTarget);
    void run(
      {
        confirmed: form.get("confirmed") === "on",
        manual: {
          claims,
          checks,
          followups: String(form.get("followups") || "")
            .split("\n")
            .map((text) => text.trim())
            .filter(Boolean),
        },
      },
      saved,
    );
  };
  const currentResult =
    result &&
    ["ACTIVE", "LOCKED"].includes(result.status) &&
    result.data.brief_id === brief.id
      ? result
      : undefined;
  return (
    <section className="artifact-card" aria-label="메시지 근거 검증">
      <h3>메시지가 경험으로 증명되는지 확인</h3>
      <p>
        원문 근거와 네 가지 기준을 대조한 뒤 메시지를 승인합니다. 확인할 질문이
        남아 있으면 메시지나 근거를 보완해 주세요.
      </p>
      {currentResult && (
        <div role="status">
          <strong>
            {currentResult.data.result === "PASSED"
              ? "근거 대조 완료 · 메시지 승인 가능"
              : "근거 또는 메시지 보완 필요"}
          </strong>
          <p className="muted">
            {currentResult.data.mode === "USER_VERIFIED"
              ? "직접 검증 기록"
              : "AI 검증 기록"}{" "}
            · 메시지 v{brief.version}
          </p>
          {((currentResult.data.checks as Data[]) || []).map((check) => (
            <p key={String(check.key)}>
              {context?.checks[String(check.key)] || String(check.key)} ·{" "}
              {check.verdict === "PASS" ? "확인" : "보완"}
              <br />
              {String(check.rationale)}
            </p>
          ))}
          {((currentResult.data.claims as Data[]) || []).map((claim, index) => (
            <p key={index}>
              <strong>{String(claim.claim)}</strong>
              <br />
              {String(claim.rationale)}
            </p>
          ))}
          {((currentResult.data.hard_issues as Data[]) || []).map(
            (issue, index) => (
              <p className="error" key={index}>
                {String(issue.message)}
              </p>
            ),
          )}
          {((currentResult.data.followups as string[]) || []).map(
            (item, index) => (
              <p key={index}>확인할 질문: {item}</p>
            ),
          )}
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!context && (
        <button
          type="button"
          className="secondary"
          onClick={() => setReload(reload + 1)}
        >
          원문 다시 불러오기
        </button>
      )}
      {ai && (
        <button type="button" disabled={busy} onClick={() => void run({})}>
          AI로 주장·근거 대조
        </button>
      )}
      {context?.brief_id === brief.id && (
        <details>
          <summary>원문을 보며 직접 검증하기</summary>
          {sourceOptions.map((source) => (
            <details key={source.key}>
              <summary>{source.title}</summary>
              <pre>{source.text}</pre>
            </details>
          ))}
          <form onSubmit={submit} key={brief.id}>
            {context.claims.map((claim, index) => (
              <fieldset key={index}>
                <legend>{claim}</legend>
                <label>
                  근거 대조 결과
                  <select
                    name={`support-${index}`}
                    defaultValue="NEEDS_VERIFICATION"
                  >
                    <option value="NEEDS_VERIFICATION">추가 확인 필요</option>
                    <option value="SUPPORTED">뒷받침됨</option>
                    <option value="PARTIALLY_SUPPORTED">일부만 뒷받침됨</option>
                    <option value="UNSUPPORTED">뒷받침되지 않음</option>
                  </select>
                </label>
                <label>
                  인용할 원문
                  <select name={`source-${index}`}>
                    {sourceOptions.map((source) => (
                      <option key={source.key} value={source.key}>
                        {source.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  주장을 뒷받침하는 구절
                  <textarea
                    name={`quote-${index}`}
                    placeholder="위 원문의 구절을 그대로 옮겨 주세요."
                  />
                </label>
                <label>
                  주장과 근거가 연결되는 이유
                  <textarea required name={`reason-${index}`} />
                </label>
              </fieldset>
            ))}
            {Object.entries(context.checks).map(([key, label]) => (
              <fieldset key={key}>
                <legend>{label}</legend>
                <label>
                  판단
                  <select
                    name={`verdict-${key}`}
                    defaultValue="NEEDS_VERIFICATION"
                  >
                    <option value="NEEDS_VERIFICATION">확인 필요</option>
                    <option value="PASS">확인함</option>
                    <option value="FAIL">보완 필요</option>
                  </select>
                </label>
                <label>
                  판단 이유
                  <textarea required name={`reason-${key}`} />
                </label>
              </fieldset>
            ))}
            <label>
              추가로 확인할 질문
              <textarea
                name="followups"
                placeholder="질문마다 한 줄씩 적어 주세요. 없으면 비워 둡니다."
              />
            </label>
            <label className="check">
              <input type="checkbox" name="confirmed" required /> 원문과 현재
              메시지를 직접 대조했습니다.
            </label>
            <button disabled={busy}>검증 결과 저장</button>
          </form>
        </details>
      )}
    </section>
  );
}
