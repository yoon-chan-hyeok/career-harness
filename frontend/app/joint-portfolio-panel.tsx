"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Request } from "./api-client";

type Material = {
  question_id: string;
  identity_role: string;
  primary_message: string;
  evidence_ids: string[];
  evidence_role: string;
  metric_ids: string[];
  climax: string;
};
type Persona = { candidate_id: string; text: string; limitation: string };
type Candidate = {
  evidence_id: string;
  title: string;
  classification: string;
  eligibility: string;
  limitations: string[];
  metrics: { id: string; data: Record<string, unknown> }[];
};
const metricLabel = (data: Record<string, unknown>) =>
  [
    String(data.name || "확인 수치"),
    String(data.value || ""),
    String(data.unit || ""),
    data.dataset ? `대상: ${String(data.dataset)}` : "",
    data.subset ? `범위: ${String(data.subset)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
type Saved = {
  id: string;
  version: number;
  status: string;
  current: boolean;
  data: {
    personas?: Persona[];
    items?: Material[];
    text?: string;
    disposition?: string;
    needs_user_edit?: boolean;
    warnings?: string[];
    proposal_mode?: string;
  };
};
type State = {
  application_id: string;
  input_revision: string;
  decision_revision: string;
  questions: { id: string; text: string }[];
  candidates: Candidate[];
  holds: string[];
  notice: string;
  strategy: { positioning: string; assignment_statement: string };
  proposal: Saved | null;
  decision: Saved | null;
  persona: Saved | null;
  portfolio: { id: string; status: string } | null;
};
type Disposition =
  "ACCEPT" | "MODIFY" | "COMBINE" | "DIRECT" | "REJECT" | "HOLD";
const choices: [Disposition, string][] = [
  ["MODIFY", "수정해서 선택"],
  ["DIRECT", "직접 작성"],
  ["COMBINE", "후보 혼합"],
  ["ACCEPT", "제안 원안 선택"],
  ["HOLD", "보류"],
  ["REJECT", "거절"],
];

export function JointPortfolioPanel({
  workspaceId,
  revisionKey,
  request,
  onSaved,
  ai = false,
  disabled = false,
  dirtyState,
}: {
  workspaceId: string;
  revisionKey: string;
  request: Request;
  onSaved: () => Promise<void>;
  ai?: boolean;
  disabled?: boolean;
  dirtyState?: { current: boolean };
}) {
  const [data, setData] = useState<State | null>(null);
  const [items, setItems] = useState<Material[]>([]);
  const [persona, setPersona] = useState("");
  const [ids, setIds] = useState<string[]>([]);
  const [mode, setMode] = useState<Disposition>("MODIFY");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const dirty = useRef(false);
  const path = `/v4/applications/${workspaceId}/portfolio`;
  const mark = (value = true) => {
    dirty.current = value;
    if (dirtyState) dirtyState.current = value;
  };
  const load = useCallback(async () => {
    const state: State = await request(path);
    if (state.application_id !== workspaceId)
      throw new Error("지원 작업이 바뀌었습니다. 다시 불러와 주세요.");
    return state;
  }, [path, request, workspaceId]);
  const restore = (state: State) => {
    setData(state);
    setItems(
      state.decision?.current && state.decision.data.items?.length
        ? state.decision.data.items
        : state.proposal?.data.items || [],
    );
    const first = state.proposal?.data.personas?.[0];
    setIds(first ? [first.candidate_id] : []);
    setPersona(
      state.persona?.current
        ? state.persona.data.text || ""
        : first?.text || "",
    );
    setReason("");
    setMode("MODIFY");
    mark(false);
  };
  useEffect(() => {
    let active = true;
    load()
      .then((state) => {
        if (!active) return;
        if (dirty.current) {
          if (state.decision_revision !== data?.decision_revision)
            setNotice(
              "자료가 바뀌었습니다. 편집 내용은 보존했습니다. 저장 전 현재 제안을 다시 확인해 주세요.",
            );
        } else restore(state);
      })
      .catch((cause) => {
        if (active && cause?.status !== 404)
          setError(
            cause instanceof Error
              ? cause.message
              : "소재 배분을 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
    // Editable state is intentionally excluded: server refresh must preserve unsaved inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load, revisionKey]);
  useEffect(
    () => () => {
      if (dirtyState) dirtyState.current = false;
    },
    [dirtyState],
  );
  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await work();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "처리하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  const generate = (useAi: boolean) =>
    run(async () => {
      if (!data) return;
      await request(`${path}/propose`, {
        expected_revision: data.input_revision,
        use_ai: useAi,
        external_transfer_confirmed: useAi,
        max_input_tokens: 8192,
      });
      restore(await load());
      await onSaved();
    });
  const save = () =>
    run(async () => {
      if (!data?.proposal) return;
      const accepted = !["HOLD", "REJECT"].includes(mode);
      await request(`${path}/decide`, {
        expected_revision: data.decision_revision,
        proposal_id: data.proposal.id,
        proposal_version: data.proposal.version,
        disposition: mode,
        persona_candidate_ids: accepted && mode !== "DIRECT" ? ids : [],
        persona_text: accepted && mode !== "ACCEPT" ? persona : "",
        items: accepted && mode !== "ACCEPT" ? items : [],
        reason,
      });
      restore(await load());
      setNotice(
        "선택을 저장했습니다. 전략 승인과 문항 전체 배분 승인은 각각 확인해 주세요.",
      );
      await onSaved();
    });
  const approve = (action: string, artifactId?: string) =>
    run(async () => {
      await request(`/applications/${workspaceId}/actions/${action}`, {
        ...(artifactId ? { artifact_id: artifactId } : {}),
      });
      restore(await load());
      await onSaved();
    });
  const update = (index: number, values: Partial<Material>) => {
    mark();
    setItems((old) =>
      old.map((i, n) => (n === index ? { ...i, ...values } : i)),
    );
  };
  if (!data) return error ? <p role="alert">{error}</p> : null;
  const rejecting = mode === "HOLD" || mode === "REJECT";
  const accepted =
    data.decision?.current &&
    !["HOLD", "REJECT"].includes(data.decision.data.disposition || "HOLD");
  return (
    <details className="joint-portfolio-panel writing-plan-panel">
      <summary>
        모든 문항의 소재·메시지 배분 <small>지원서별 선택</small>
      </summary>
      <p>{data.notice}</p>
      <p>
        현재 전략: {data.strategy.positioning} · 맡길 일:{" "}
        {data.strategy.assignment_statement}
      </p>
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {data.holds.map((text) => (
        <p key={text} role="status">
          {text}
        </p>
      ))}
      <div className="writing-plan-actions">
        <button
          type="button"
          disabled={busy || disabled || dirty.current || !!data.holds.length}
          onClick={() => void generate(false)}
        >
          직접 작성표 열기
        </button>
        {ai && (
          <button
            type="button"
            disabled={busy || disabled || dirty.current || !!data.holds.length}
            onClick={() => void generate(true)}
          >
            AI로 소재 배분 제안
          </button>
        )}
        <button
          type="button"
          disabled={busy || disabled}
          onClick={() =>
            void run(async () => {
              restore(await load());
              setNotice("미저장 입력을 버리고 현재 기준을 불러왔습니다.");
            })
          }
        >
          입력 버리고 현재 기준 불러오기
        </button>
      </div>
      <p className="muted">
        작성표는 초안이 아닙니다. AI 제안을 누르면 현재 문항·사용 가능한 본인
        근거를 연결된 AI로 전송합니다. 기존 동의·사용 한도를 적용합니다. 같은
        프로젝트도 다른 수행·메시지·핵심 장면으로 나눌 수 있습니다. 의미가
        겹치는지는 전체 검수에서 다시 확인합니다.
      </p>
      {data.proposal && (
        <>
          <p>
            제안 v{data.proposal.version} ·{" "}
            {data.proposal.current
              ? "현재 기준"
              : "기준 변경: 제안을 다시 만드세요"}{" "}
            ·{" "}
            {data.proposal.data.proposal_mode === "AI_PROPOSED"
              ? "AI 검토 제안"
              : "직접 편집할 작성표"}
          </p>
          {(data.proposal.data.warnings || []).map((text) => (
            <p key={text}>{text}</p>
          ))}
          <label>
            처리 방법
            <select
              value={mode}
              disabled={busy || disabled}
              onChange={(e) => {
                mark();
                setMode(e.target.value as Disposition);
              }}
            >
              {choices.map(([value, label]) => (
                <option
                  key={value}
                  value={value}
                  disabled={
                    value === "ACCEPT" && data.proposal?.data.needs_user_edit
                  }
                >
                  {label}
                </option>
              ))}
            </select>
          </label>
          {!rejecting && (
            <>
              <fieldset disabled={busy || disabled}>
                <legend>이번 지원서에서 보여줄 나의 역할</legend>
                {(data.proposal.data.personas || []).map((candidate) => (
                  <label key={candidate.candidate_id}>
                    <input
                      type="checkbox"
                      checked={ids.includes(candidate.candidate_id)}
                      onChange={(e) => {
                        mark();
                        setIds((old) =>
                          e.target.checked
                            ? [...old, candidate.candidate_id]
                            : old.filter((id) => id !== candidate.candidate_id),
                        );
                      }}
                    />
                    {candidate.text}
                    <small className="muted"> · {candidate.limitation}</small>
                  </label>
                ))}
                <label>
                  선택·수정한 Persona
                  <textarea
                    aria-label="선택한 Persona"
                    value={persona}
                    disabled={mode === "ACCEPT"}
                    onChange={(e) => {
                      mark();
                      setPersona(e.target.value);
                    }}
                  />
                </label>
              </fieldset>
              <div className="joint-material-grid">
                {items.map((item, index) => (
                  <fieldset
                    key={item.question_id}
                    disabled={busy || disabled || mode === "ACCEPT"}
                  >
                    <legend>
                      {index + 1}번 ·{" "}
                      {
                        data.questions.find((q) => q.id === item.question_id)
                          ?.text
                      }
                    </legend>
                    {(
                      [
                        ["identity_role", "이 문항의 역할"],
                        ["primary_message", "핵심 메시지"],
                        ["evidence_role", "이 경험에서 보여줄 본인 수행"],
                        ["climax", "가장 중요한 판단·결과 장면"],
                      ] as const
                    ).map(([field, label]) => (
                      <label key={field}>
                        {label}
                        <textarea
                          aria-label={`${index + 1}번 ${label}`}
                          value={item[field]}
                          onChange={(e) =>
                            update(index, { [field]: e.target.value })
                          }
                        />
                      </label>
                    ))}
                    <p>
                      사용할 본인 근거 · 표현 참고는 사실로 승인되지 않습니다.
                    </p>
                    {data.candidates.map((candidate) => (
                      <label key={candidate.evidence_id}>
                        <input
                          type="checkbox"
                          disabled={candidate.eligibility !== "ELIGIBLE"}
                          checked={item.evidence_ids.includes(
                            candidate.evidence_id,
                          )}
                          onChange={(e) => {
                            const evidenceIds = e.target.checked
                              ? [...item.evidence_ids, candidate.evidence_id]
                              : item.evidence_ids.filter(
                                  (id) => id !== candidate.evidence_id,
                                );
                            const metrics = new Set(
                              data.candidates
                                .filter((c) =>
                                  evidenceIds.includes(c.evidence_id),
                                )
                                .flatMap((c) => c.metrics.map((m) => m.id)),
                            );
                            update(index, {
                              evidence_ids: evidenceIds,
                              metric_ids: item.metric_ids.filter((id) =>
                                metrics.has(id),
                              ),
                            });
                          }}
                        />
                        {candidate.title} ·{" "}
                        {candidate.classification === "DIRECT"
                          ? "직접 근거"
                          : candidate.classification === "ADJACENT"
                            ? "인접 근거"
                            : "직무 근거 없음"}
                        {candidate.eligibility !== "ELIGIBLE" && (
                          <small>
                            {" "}
                            · 확인 필요: {candidate.limitations.join(" / ")}
                          </small>
                        )}
                      </label>
                    ))}
                    {data.candidates
                      .filter((c) => item.evidence_ids.includes(c.evidence_id))
                      .flatMap((c) => c.metrics)
                      .map((metric) => (
                        <label key={metric.id}>
                          <input
                            type="checkbox"
                            checked={item.metric_ids.includes(metric.id)}
                            onChange={(e) =>
                              update(index, {
                                metric_ids: e.target.checked
                                  ? [...item.metric_ids, metric.id]
                                  : item.metric_ids.filter(
                                      (id) => id !== metric.id,
                                    ),
                              })
                            }
                          />
                          사용할 확인 수치: {metricLabel(metric.data)}
                        </label>
                      ))}
                  </fieldset>
                ))}
              </div>
            </>
          )}
          <label>
            {rejecting ? "거절·보류 이유" : "선택·수정 메모"}
            <textarea
              aria-label="선택 이유"
              value={reason}
              disabled={busy || disabled}
              onChange={(e) => {
                mark();
                setReason(e.target.value);
              }}
            />
          </label>
          <button
            type="button"
            disabled={
              busy ||
              disabled ||
              !data.proposal.current ||
              (rejecting && !reason.trim())
            }
            onClick={() => void save()}
          >
            {rejecting ? "거절·보류 기록" : "선택 저장 (승인은 별도)"}
          </button>
        </>
      )}
      {data.decision && (
        <p>
          선택 v{data.decision.version} ·{" "}
          {data.decision.current
            ? data.decision.data.disposition
            : "다시 확인 필요"}
        </p>
      )}
      {accepted && (
        <div className="writing-plan-actions">
          <button
            type="button"
            disabled={
              busy ||
              disabled ||
              dirty.current ||
              data.persona?.status === "LOCKED"
            }
            onClick={() => void approve("approve-strategy")}
          >
            Persona·기존 전략 함께 확인 후 승인
          </button>
          <button
            type="button"
            disabled={
              busy ||
              disabled ||
              dirty.current ||
              data.persona?.status !== "LOCKED" ||
              data.portfolio?.status === "LOCKED"
            }
            onClick={() =>
              void approve("approve-portfolio", data.portfolio?.id)
            }
          >
            모든 문항 배분 확인 후 승인
          </button>
        </div>
      )}
    </details>
  );
}
