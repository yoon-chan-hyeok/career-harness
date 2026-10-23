"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Request } from "./api-client";

type Policy = {
  maximum: number;
  minimum: number | null;
  unit: "CHARACTERS" | "BYTES";
  spaces: "INCLUDED" | "EXCLUDED" | "UNKNOWN";
  newlines: "INCLUDED" | "EXCLUDED" | "UNKNOWN";
  title: "INCLUDED" | "EXCLUDED" | "UNKNOWN";
  encoding: "UTF-8" | "EUC-KR" | "UNKNOWN";
};
type Part = { content: string; suggested_budget: number };
type Candidate = {
  guide_id: string;
  guide_version: number;
  guide_snapshot_hash: string;
  match_type: string;
  intent: string;
  ranking_explanation: string;
  source_ref: string;
  scope_transfer: boolean;
  count_policy_confirmation_required: boolean;
  suggested_allocation: Part[];
};
type Preview = {
  question_contract: {
    raw_text: string;
    required_demands: string[];
    excluded_topics: string[];
    length: Policy;
  };
  contract_state_revision: string;
  needs_reconfirmation: boolean;
  catalog_status: string;
  selection_revision: string;
  selection: {
    notice?: string;
    current?: boolean;
    guide_id?: string | null;
    allocation_budgets?: number[];
  } | null;
  retrieval: {
    request_key: string;
    candidates: Candidate[];
    fallback: { intent: string; allocation: Part[] };
  };
};
const lines = (text: string) =>
  text
    .split("\n")
    .map((v) => v.trim())
    .filter(Boolean);
const message = (e: unknown) =>
  e instanceof Error ? e.message : "문항 기준을 다시 확인해 주세요.";

export function QuestionGuideChoice({
  workspaceId,
  questionId,
  revision,
  request,
  onSaved,
  disabled,
  onDirtyChange,
}: {
  workspaceId: string;
  questionId: string;
  revision: string;
  request: Request;
  onSaved: () => Promise<void>;
  disabled: boolean;
  onDirtyChange: (dirty: boolean) => void;
}) {
  const path = `/v4/applications/${encodeURIComponent(workspaceId)}/questions/${encodeURIComponent(questionId)}`;
  const [state, setState] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState("fallback");
  const [budgets, setBudgets] = useState<number[]>([]);
  const [demands, setDemands] = useState("");
  const [excluded, setExcluded] = useState("");
  const [policy, setPolicy] = useState<Policy | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [baseline, setBaseline] = useState("");
  const localDirty = useRef(false);
  const load = useCallback(
    () => request(path + "/guides") as Promise<Preview>,
    [path, request],
  );
  function install(next: Preview) {
    setState(next);
    setPolicy(next.question_contract.length);
    setDemands(next.question_contract.required_demands.join("\n"));
    setExcluded(next.question_contract.excluded_topics.join("\n"));
    setConfirmed(false);
    const selectedId = next.selection?.current
      ? next.selection.guide_id || "fallback"
      : "fallback";
    const parts =
      next.retrieval.candidates.find((c) => c.guide_id === selectedId)
        ?.suggested_allocation || next.retrieval.fallback.allocation;
    const counts =
      next.selection?.current && next.selection.allocation_budgets
        ? next.selection.allocation_budgets
        : parts.map((p) => p.suggested_budget);
    setSelected(selectedId);
    setBudgets(counts);
    setBaseline(JSON.stringify([selectedId, counts]));
    localDirty.current = false;
  }
  useEffect(() => {
    let active = true;
    if (localDirty.current) {
      setError(
        "관련 자료가 바뀌었습니다. 입력은 유지했으니 현재 기준을 새로 불러온 뒤 다시 확인해 주세요.",
      );
      return;
    }
    setState(null);
    setError("");
    setNotice("");
    load()
      .then((next) => {
        if (active) install(next);
      })
      .catch((e) => {
        if (active) setError(message(e));
      });
    return () => {
      active = false;
    };
  }, [load, revision]);
  const candidate = state?.retrieval.candidates.find(
    (c) => c.guide_id === selected,
  );
  const allocation =
    candidate?.suggested_allocation ||
    state?.retrieval.fallback.allocation ||
    [];
  const blocked = disabled || busy || !state;
  const contractChanged =
    state &&
    (JSON.stringify(policy) !==
      JSON.stringify(state.question_contract.length) ||
      JSON.stringify(lines(demands)) !==
        JSON.stringify(state.question_contract.required_demands) ||
      JSON.stringify(lines(excluded)) !==
        JSON.stringify(state.question_contract.excluded_topics));
  const dirty =
    !!state &&
    (!!contractChanged || JSON.stringify([selected, budgets]) !== baseline);
  useEffect(() => {
    localDirty.current = dirty;
    onDirtyChange(dirty);
  }, [dirty, onDirtyChange]);
  useEffect(() => () => onDirtyChange(false), [onDirtyChange]);
  function choose(id: string) {
    if (!state) return;
    setSelected(id);
    const parts =
      state.retrieval.candidates.find((c) => c.guide_id === id)
        ?.suggested_allocation || state.retrieval.fallback.allocation;
    setBudgets(parts.map((p) => p.suggested_budget));
  }
  async function submit(kind: "contract" | "guide-choice") {
    if (!state || !policy || blocked) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request(
        path + "/" + kind,
        kind === "contract"
          ? {
              expected_revision: state.contract_state_revision,
              length: policy,
              required_demands: lines(demands),
              excluded_topics: lines(excluded),
              confirmed: true,
            }
          : {
              expected_revision: state.selection_revision,
              request_key: state.retrieval.request_key,
              guide_id: candidate?.guide_id ?? null,
              guide_version: candidate?.guide_version ?? null,
              guide_snapshot_hash: candidate?.guide_snapshot_hash ?? null,
              allocation_budgets: budgets,
            },
      );
      install(await load());
      await onSaved();
      setNotice(
        kind === "contract"
          ? "문항 기준을 저장했습니다. 아래에서 참고 구성을 선택해 주세요."
          : "선택한 구성과 분량을 저장했습니다. 메시지·근거 승인과 문항 간 배분은 별도로 확인합니다.",
      );
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="writing-plan-details guide-choice-panel">
      <summary>문항 요구 확인 · 참고 구성 선택</summary>
      <button
        type="button"
        className="text-button"
        disabled={busy || disabled}
        onClick={async () => {
          setBusy(true);
          try {
            install(await load());
            setError("");
          } catch (e) {
            setError(message(e));
          } finally {
            setBusy(false);
          }
        }}
      >
        {dirty
          ? "입력 버리고 현재 기준 새로 불러오기"
          : "현재 기준 새로 불러오기"}
      </button>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {!state && !error && (
        <p role="status">현재 문항과 참고 구성을 확인하고 있어요…</p>
      )}
      {state && policy && (
        <>
          <p className="muted">
            현재 질문이 우선입니다. 참고 구성의 기관·프로젝트·수치는 본인의
            사실이 되지 않아요.
          </p>
          <blockquote>{state.question_contract.raw_text}</blockquote>
          {(state.needs_reconfirmation || state.selection?.notice) && (
            <p role="status">
              {state.selection?.notice ||
                "현재 문항 기준을 다시 확인해 주세요."}
            </p>
          )}
          <fieldset disabled={blocked}>
            <legend>제출 폼에서 확인한 조건</legend>
            <label>
              반드시 답할 요구 · 한 줄에 하나
              <textarea
                value={demands}
                maxLength={8000}
                onChange={(e) => setDemands(e.target.value)}
              />
            </label>
            <label>
              제외할 주제 · 한 줄에 하나
              <textarea
                value={excluded}
                maxLength={8000}
                onChange={(e) => setExcluded(e.target.value)}
              />
            </label>
            <div className="guide-policy-grid">
              <label>
                단위
                <select
                  value={policy.unit}
                  onChange={(e) =>
                    setPolicy({
                      ...policy,
                      unit: e.target.value as Policy["unit"],
                    })
                  }
                >
                  <option value="CHARACTERS">글자</option>
                  <option value="BYTES">바이트</option>
                </select>
              </label>
              {(["spaces", "newlines", "title"] as const).map((key, i) => (
                <label key={key}>
                  {["공백", "줄바꿈", "제목"][i]}
                  <select
                    value={policy[key]}
                    onChange={(e) =>
                      setPolicy({ ...policy, [key]: e.target.value })
                    }
                  >
                    <option value="UNKNOWN">미확인</option>
                    <option value="INCLUDED">포함</option>
                    <option value="EXCLUDED">제외</option>
                  </select>
                </label>
              ))}
              <label>
                최소 분량
                <input
                  type="number"
                  min={0}
                  max={policy.maximum}
                  value={policy.minimum ?? ""}
                  onChange={(e) =>
                    setPolicy({
                      ...policy,
                      minimum:
                        e.target.value === "" ? null : Number(e.target.value),
                    })
                  }
                />
              </label>
            </div>
            <p className="muted">
              현재 등록한 상한 {policy.maximum.toLocaleString()}
              {policy.unit === "BYTES" ? "바이트" : "자"}. 바이트·공백 제외 등
              별도 계수 방식은 저장 후 자동 작성·잠금이 보류됩니다.
            </p>
            <label>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              현재 문항과 제출 폼에서 위 조건을 직접 확인했습니다.
            </label>
            <button
              type="button"
              disabled={!confirmed || blocked}
              onClick={() => submit("contract")}
            >
              문항 기준 확인 저장
            </button>
          </fieldset>
          <fieldset
            disabled={
              blocked || state.needs_reconfirmation || !!contractChanged
            }
          >
            <legend>이번 문항에 참고할 구성</legend>
            <label className="guide-choice-option">
              <input
                type="radio"
                name={`guide-${questionId}`}
                checked={selected === "fallback"}
                onChange={() => choose("fallback")}
              />
              현재 문항에 맞춘 기본 구성
            </label>
            {state.retrieval.candidates.map((c) => (
              <div className="guide-choice-option" key={c.guide_id}>
                <label>
                  <input
                    type="radio"
                    name={`guide-${questionId}`}
                    checked={selected === c.guide_id}
                    onChange={() => choose(c.guide_id)}
                  />
                  {c.match_type === "EXACT"
                    ? "동일 문항의 구조 참고"
                    : "유사 문항에서 참고한 제안"}
                </label>
                <p>{c.intent}</p>
                <p className="muted">{c.ranking_explanation}</p>
                {c.scope_transfer && <p>현재 회사의 공식 지침이 아닙니다.</p>}
                {c.count_policy_confirmation_required && (
                  <p>계수 정책 확인이 필요합니다.</p>
                )}
                <a href={c.source_ref} target="_blank" rel="noreferrer">
                  참고 출처 ↗
                </a>
              </div>
            ))}
            {!state.retrieval.candidates.length && (
              <p className="muted">
                검토된 적합 가이드가 없어 현재 문항의 기본 구성을 제안합니다.
              </p>
            )}
            {state.catalog_status === "UNAVAILABLE" && (
              <p role="status">
                참고 자료를 불러오지 못했습니다. 기존 선택이 있다면 다시 확인이
                필요합니다.
              </p>
            )}
            <ol className="writing-plan-allocation">
              {allocation.map((part, i) => (
                <li key={i}>
                  <label>
                    {part.content}
                    <input
                      type="number"
                      min={1}
                      max={policy.maximum}
                      value={budgets[i] ?? ""}
                      aria-label={`${part.content} 권장 분량`}
                      onChange={(e) =>
                        setBudgets(
                          budgets.map((v, n) =>
                            n === i ? Number(e.target.value) : v,
                          ),
                        )
                      }
                    />
                  </label>
                </li>
              ))}
            </ol>
            <p>
              배분 합계{" "}
              {budgets.reduce((sum, v) => sum + v, 0).toLocaleString()} /{" "}
              {policy.maximum.toLocaleString()}
              {policy.unit === "BYTES" ? "바이트" : "자"} · 고정 문단 수가
              아닙니다.
            </p>
            <button
              type="button"
              disabled={
                blocked ||
                budgets.some((v) => !Number.isInteger(v) || v <= 0) ||
                budgets.reduce((s, v) => s + v, 0) > policy.maximum
              }
              onClick={() => submit("guide-choice")}
            >
              이 구성과 분량으로 선택
            </button>
          </fieldset>
          {contractChanged && (
            <p role="status">변경한 문항 기준을 먼저 확인하고 저장해 주세요.</p>
          )}
          {disabled && (
            <p className="muted">
              작성 메모 변경사항을 먼저 저장한 뒤 참고 구성을 바꿔 주세요.
            </p>
          )}
        </>
      )}
      {notice && <p role="status">{notice}</p>}
    </details>
  );
}
