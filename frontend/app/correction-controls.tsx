"use client";
import { useEffect, useState } from "react";
import type { Workspace } from "./workroom";

type Request = (path: string, body?: unknown, method?: string) => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Proposal = {
  id: string;
  data: {
    artifact_kind: string;
    reason: string;
    old_fields: Record<string, unknown>;
    new_fields: Record<string, unknown>;
  };
};
const labels: Record<string, string> = {
  actual_outputs: "실제 업무",
  base_profession: "본업",
  main_skills: "핵심 역량",
  differentiators: "차별점",
  output_importance: "업무 중요도",
  positioning: "포지셔닝",
  assignment_statement: "맡길 수 있는 일",
  main_skill_message: "핵심 메시지",
  base_profession_identity: "본업 정체성",
};
const format = (value: unknown): string =>
  typeof value === "string"
    ? value
    : Array.isArray(value)
      ? value.map(format).join(" · ")
      : JSON.stringify(value);

export function CorrectionInbox({
  workspace,
  request,
  refresh,
}: {
  workspace: Workspace;
  request: Request;
  refresh: () => Promise<void>;
}) {
  const [items, setItems] = useState<Proposal[]>([]),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    request(`/applications/${workspace.id}/correction-proposals`)
      .then((value) => {
        if (active) {
          setItems(value);
          setError("");
        }
      })
      .catch((error) => {
        if (active)
          setError(
            error instanceof Error
              ? error.message
              : "교정안을 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, [workspace, request]);
  async function decide(id: string, reject: boolean) {
    setBusy(true);
    setError("");
    try {
      await request(
        `/applications/${workspace.id}/correction-proposals/${id}`,
        { reject, confirmed: !reject },
      );
      await refresh();
    } catch (error) {
      setError(error instanceof Error ? error.message : "반영하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  }
  return items.length || error ? (
    <section>
      <h3>직무 해석 교정안</h3>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {items.map((item) => (
        <article key={item.id} className="card">
          <p>{item.data.reason}</p>
          {Object.keys(item.data.new_fields).map((field) => (
            <div key={field}>
              <strong>{labels[field] || field}</strong>
              <p className="muted">
                수정 전: {format(item.data.old_fields[field])}
              </p>
              <p>수정 후: {format(item.data.new_fields[field])}</p>
            </div>
          ))}
          <p className="muted">
            반영하면 관련 전략과 문서는 재검토가 필요합니다.
          </p>
          <button disabled={busy} onClick={() => void decide(item.id, false)}>
            이 교정안 반영
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void decide(item.id, true)}
          >
            거절
          </button>
        </article>
      ))}
    </section>
  ) : null;
}

type Candidate = {
  id: string;
  data: {
    rule: string;
    scope_type: string;
    scope_value: string;
    source_case_ids: string[];
  };
};
type Evaluation = {
  id: string;
  data: {
    status: string;
    checks_executed?: number;
    results: { passed: boolean; reason: string }[];
  };
};
export function RuleControls({ request }: { request: Request }) {
  const [cases, setCases] = useState<
    { id: string; stage: string; before: unknown; after: unknown }[]
  >([]);
  const [caseIds, setCaseIds] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]),
    [evaluations, setEvaluations] = useState<Record<string, Evaluation>>({});
  const [rule, setRule] = useState(""),
    [consent, setConsent] = useState(false),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  useEffect(() => {
    let active = true;
    request("/rules/candidates")
      .then((value) => {
        if (active) setCandidates(value);
      })
      .catch((error) => {
        if (active)
          setMessage(
            error instanceof Error
              ? error.message
              : "규칙을 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, [request]);
  async function act(task: () => Promise<void>) {
    setBusy(true);
    setMessage("");
    try {
      await task();
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "반영하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    let active = true;
    request("/rules/correction-cases")
      .then((value) => {
        if (active) setCases(value);
      })
      .catch(() => {});
    return () => {
      active = false;
    };
  }, [request]);
  return (
    <section>
      <h3>내 작성 선호와 학습 후보</h3>
      <p>
        직접 지정한 선호는 내 작성 규칙으로 저장합니다. 학습 후보는 서로 다른
        교정 사례와 과거 사례 검증을 거친 뒤 승인할 수 있습니다.
      </p>
      <label>
        직접 지정할 선호
        <textarea
          value={rule}
          onChange={(event) => setRule(event.target.value)}
          placeholder="예: 이력서 첫 문장은 직접 수행한 판단으로 시작"
        />
      </label>
      <button
        disabled={busy || !rule.trim()}
        onClick={() =>
          void act(async () => {
            await request("/rules/preferences", { rule, confirmed: true });
            setRule("");
            setMessage("내 작성 선호를 저장했습니다.");
          })
        }
      >
        내 선호로 저장
      </button>
      {cases.length > 0 && (
        <details>
          <summary>반복 교정에서 작성 규칙 제안</summary>
          <p className="muted">
            같은 선호를 보여 주는 서로 다른 교정 사례를 2건 이상 고르세요.
          </p>
          {cases.map((item, index) => (
            <label className="checkbox" key={item.id}>
              <input
                type="checkbox"
                checked={caseIds.includes(item.id)}
                onChange={(event) =>
                  setCaseIds((previous) =>
                    event.target.checked
                      ? [...previous, item.id]
                      : previous.filter((id) => id !== item.id),
                  )
                }
              />
              교정 사례 {index + 1} · {item.stage}
              <details>
                <summary>수정 전후 보기</summary>
                <p>{format(item.before)}</p>
                <p>{format(item.after)}</p>
              </details>
            </label>
          ))}
          <button
            disabled={
              busy || !consent || caseIds.length < 2 || caseIds.length > 20
            }
            onClick={() =>
              void act(async () => {
                const candidate = await request("/rules/candidates/propose", {
                  source_case_ids: caseIds,
                  confirmed_external_eval: true,
                });
                setCandidates((previous) => [
                  ...previous.filter((item) => item.id !== candidate.id),
                  candidate,
                ]);
                setMessage(
                  "규칙 후보를 제안했습니다. 과거 사례 검증과 승인은 별도로 필요합니다.",
                );
              })
            }
          >
            선택한 교정에서 후보 제안
          </button>
        </details>
      )}
      {(candidates.length > 0 || cases.length > 0) && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={consent}
            onChange={(event) => setConsent(event.target.checked)}
          />
          규칙 후보와 연결된 교정 사례를 AI로 검증하는 데 동의
        </label>
      )}
      {candidates.map((candidate) => {
        const evaluation = evaluations[candidate.id];
        return (
          <article className="card" key={candidate.id}>
            <p>{candidate.data.rule}</p>
            <p className="muted">
              적용 범위: {candidate.data.scope_type} ·{" "}
              {candidate.data.scope_value || "공통"} / 근거{" "}
              {candidate.data.source_case_ids?.length || 0}건
            </p>
            <button
              disabled={busy || !consent}
              onClick={() =>
                void act(async () => {
                  const result = await request(
                    `/rules/candidates/${candidate.id}/evaluate`,
                    { confirmed_external_eval: true },
                  );
                  setEvaluations((previous) => ({
                    ...previous,
                    [candidate.id]: result,
                  }));
                })
              }
            >
              과거 교정 사례로 검증
            </button>
            {evaluation && (
              <>
                <p>
                  {evaluation.data.status === "PASSED"
                    ? "검증 통과 · 직접 승인 대기"
                    : "검증 실패 · 자동 적용되지 않음"}{" "}
                  ({evaluation.data.checks_executed || 0}건)
                </p>
                {evaluation.data.results
                  .filter((item) => !item.passed)
                  .map((item, index) => (
                    <p className="muted" key={index}>
                      {item.reason}
                    </p>
                  ))}
                <button
                  disabled={busy || evaluation.data.status !== "PASSED"}
                  onClick={() =>
                    void act(async () => {
                      await request(
                        `/rules/candidates/${candidate.id}/promote`,
                        { evaluation_id: evaluation.id, confirmed: true },
                      );
                      setCandidates((previous) =>
                        previous.filter((item) => item.id !== candidate.id),
                      );
                      setMessage("검증한 규칙을 승인했습니다.");
                    })
                  }
                >
                  검증 결과 확인 · 적용 승인
                </button>
              </>
            )}
          </article>
        );
      })}
      {message && <p role="status">{message}</p>}
    </section>
  );
}
