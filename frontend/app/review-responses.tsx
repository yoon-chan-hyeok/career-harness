"use client";

import { FormEvent, useContext, useEffect, useState } from "react";
import { EditorSaveContext } from "./editor-dialog";
import { sources, type Evidence } from "./claim-evidence-test";
import type { Artifact } from "./workroom";

type Citation = { evidence_id: string; record_id?: string; quote: string };
type Task = { id: string; text: string; category: string; priority: string };
type Entry = {
  task_id: string;
  action: string;
  answer: string;
  rationale: string;
  citations: Citation[];
  status?: string;
  verification_rationale?: string;
};
type Context = {
  review_id: string;
  review_version: number;
  tasks: Task[];
  actions: Record<string, string>;
  evidence: Evidence[];
};

export function responsesComplete(review?: Artifact, result?: Artifact) {
  if (!review || !["ACTIVE", "LOCKED"].includes(review.status)) return false;
  const tasks = review.data.response_tasks;
  const needed = Array.isArray(tasks)
    ? tasks.length > 0
    : Array.isArray(review.data.followups) && review.data.followups.length > 0;
  return (
    !needed ||
    Boolean(
      result &&
      ["ACTIVE", "LOCKED"].includes(result.status) &&
      result.data.review_id === review.id &&
      result.data.status === "RESOLVED",
    )
  );
}

function AnswerFields({
  task,
  prefix,
  entry,
  context,
}: {
  task: Task;
  prefix: string;
  entry?: Entry;
  context: Context;
}) {
  const [count, setCount] = useState(Math.max(1, entry?.citations.length || 0));
  const options = sources(context.evidence);
  return (
    <fieldset className="review-answer-fields" data-review-task={task.id}>
      <legend>{task.text}</legend>
      <p className="muted">
        {task.category === "GROUNDING"
          ? "사실 확인 · 현재 원문으로 답하거나 문서·근거를 보완해 주세요."
          : task.category === "JOB_MOTIVATION"
            ? "본업과 지원 의향을 자신의 말로 설명해 주세요."
            : "문서 보완, 근거 보완, 면접 준비, 공백 인정 중 처리 방법을 정해 주세요."}
      </p>
      <label>
        처리 방법
        <select name={`${prefix}-action`} defaultValue={entry?.action || ""}>
          <option value="">선택해 주세요</option>
          {Object.entries(context.actions).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
      </label>
      <label>
        내 답변 또는 구체적인 보완 내용
        <textarea
          name={`${prefix}-answer`}
          defaultValue={entry?.answer || ""}
          maxLength={10000}
        />
      </label>
      <label>
        이 방법으로 처리하는 이유
        <textarea
          name={`${prefix}-rationale`}
          defaultValue={entry?.rationale || ""}
          maxLength={5000}
        />
      </label>
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="review-citation">
          <label>
            인용할 원문 {index + 1}
            <select
              name={`${prefix}-source-${index}`}
              defaultValue={
                entry?.citations[index]?.record_id ||
                entry?.citations[index]?.evidence_id ||
                ""
              }
            >
              <option value="">인용 없음</option>
              {options.map((source) => (
                <option key={source.key} value={source.key}>
                  {source.title}
                </option>
              ))}
            </select>
          </label>
          <label>
            답변을 뒷받침하는 구절 {index + 1}
            <textarea
              name={`${prefix}-quote-${index}`}
              defaultValue={entry?.citations[index]?.quote || ""}
              placeholder="위 원문에서 해당 구절을 그대로 옮겨 주세요."
            />
          </label>
        </div>
      ))}
      <button
        type="button"
        className="secondary"
        onClick={() => setCount((value) => value + 1)}
      >
        근거 인용 추가
      </button>
    </fieldset>
  );
}

export function ReviewResponsePanel({
  workspaceId,
  review,
  result,
  ai,
  request,
  act,
  editable = true,
}: {
  workspaceId: string;
  review?: Artifact;
  result?: Artifact;
  ai: boolean;
  request: <T>(path: string, body?: object, method?: string) => Promise<T>;
  act: (action: string, body: object) => Promise<unknown>;
  editable?: boolean;
}) {
  const [context, setContext] = useState<Context | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const editor = useContext(EditorSaveContext);
  const resume = review?.kind === "ResumeReview";
  const reviewId = review?.id;
  const slot = review?.slot || "";
  const active = Boolean(
    review && ["ACTIVE", "LOCKED"].includes(review.status),
  );
  useEffect(() => {
    let cancelled = false;
    setContext(null);
    if (active) {
      request<Context>(
        `/applications/${workspaceId}/review-response-context?qid=${encodeURIComponent(slot)}&resume=${resume}`,
      )
        .then((value) => {
          if (!cancelled) {
            setContext(value);
            setError("");
          }
        })
        .catch((reason) => {
          if (!cancelled)
            setError(
              reason instanceof Error
                ? reason.message
                : "현재 검수 질문을 불러오지 못했습니다.",
            );
        });
    }
    return () => {
      cancelled = true;
    };
  }, [active, request, workspaceId, slot, resume, reviewId, reload]);
  if (!review) return null;
  const currentResult =
    result &&
    ["ACTIVE", "LOCKED"].includes(result.status) &&
    result.data.review_id === review.id
      ? result
      : undefined;
  const entries = (currentResult?.data.entries || []) as Entry[];
  const ready = active && context?.review_id === review.id;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!ready || !context || busy || !editable) return;
    const element = event.currentTarget;
    const data = new FormData(element);
    const manual =
      (event.nativeEvent as SubmitEvent).submitter?.getAttribute("value") !==
      "ai";
    setError("");
    try {
      if (manual && data.get("review-confirmed") !== "on")
        throw new Error("답변과 원문을 직접 대조한 뒤 확인을 선택해 주세요.");
      const options = sources(context.evidence);
      const answered: Entry[] = [];
      for (const task of context.tasks) {
        const prefix = `review-${review.id}-${task.id}`;
        const action = String(data.get(`${prefix}-action`) || "");
        const answer = String(data.get(`${prefix}-answer`) || "").trim();
        const rationale = String(data.get(`${prefix}-rationale`) || "").trim();
        const citations: Citation[] = [];
        for (const [name, value] of data) {
          if (!name.startsWith(`${prefix}-source-`)) continue;
          const index = name.slice(`${prefix}-source-`.length);
          const quote = String(data.get(`${prefix}-quote-${index}`) || "");
          const source = options.find((option) => option.key === value);
          if (quote.trim() && !source)
            throw new Error("인용 구절에 연결할 원문을 선택해 주세요.");
          if (source && !quote.trim())
            throw new Error("선택한 원문의 인용 구절을 적어 주세요.");
          if (source && quote.trim())
            citations.push({
              evidence_id: source.evidenceId,
              record_id: source.recordId,
              quote,
            });
        }
        if (!action && !answer && !rationale && !citations.length) continue;
        if (!action || !answer || !rationale)
          throw new Error(
            `“${task.text}”의 처리 방법, 답변과 이유를 함께 적어 주세요.`,
          );
        answered.push({
          task_id: task.id,
          action,
          answer,
          rationale,
          citations,
        });
      }
      if (!answered.length)
        throw new Error("저장할 답변을 한 개 이상 적어 주세요.");
      const saved = editor.beginSave(element);
      setBusy(true);
      await act("review-answers", {
        qid: slot,
        resume,
        manual_verified: manual,
        responses: {
          review_id: review.id,
          review_version: review.version,
          entries: answered,
          confirmed: manual,
        },
      });
      saved();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "답변을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section
      className="artifact-card review-response-panel"
      aria-label="검수 질문 답변"
    >
      <h3>검수 질문에 답하고 보완 방법 정하기</h3>
      <p>
        답변은 질문별로 나누어 저장할 수 있습니다. 문서·근거 보완을 선택하면
        실제 수정과 재검수 뒤 최종 잠금합니다.
      </p>
      {!active && (
        <p className="note">
          본문이나 근거가 바뀌었습니다. 현재 문서를 다시 검수해 주세요.
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {active && !ready && (
        <button
          type="button"
          className="secondary"
          onClick={() => setReload((value) => value + 1)}
        >
          검수 질문 다시 불러오기
        </button>
      )}
      {currentResult && (
        <div role="status">
          <strong>
            {currentResult.data.status === "RESOLVED"
              ? "검수 질문 처리 완료 · 문서를 읽고 최종 잠금해 주세요."
              : "답변 또는 보완이 남아 있습니다."}
          </strong>
          <p className="muted">
            {currentResult.data.mode === "USER_VERIFIED"
              ? "직접 대조한 기록"
              : currentResult.data.mode === "MIXED_REVIEW"
                ? "직접 대조와 AI 확인을 함께 사용한 기록"
                : "AI 확인 기록"}{" "}
            · 검수 v{review.version}
          </p>
          {entries.map((entry) => (
            <p key={entry.task_id}>
              <strong>
                {entry.status === "RESOLVED" ? "확인됨" : "보완 필요"}
              </strong>{" "}
              · {context?.tasks.find((t) => t.id === entry.task_id)?.text}
              <br />
              {entry.verification_rationale}
            </p>
          ))}
        </div>
      )}
      {ready && context && !context.tasks.length && (
        <p>현재 검수에서 추가 답변을 요청한 질문은 없습니다.</p>
      )}
      {ready && context && context.tasks.length > 0 && (
        <>
          <details>
            <summary>선택한 경험의 원문 확인</summary>
            {sources(context.evidence).map((source) => (
              <details key={source.key}>
                <summary>{source.title}</summary>
                <pre>{source.text}</pre>
              </details>
            ))}
          </details>
          <form
            key={`${review.id}:${currentResult?.id || "new"}`}
            onSubmit={(event) => void submit(event)}
          >
            <fieldset
              disabled={busy || !editable}
              className="review-response-form"
            >
              {context.tasks.map((task) => (
                <AnswerFields
                  key={`${task.id}:${currentResult?.id || "new"}`}
                  task={task}
                  prefix={`review-${review.id}-${task.id}`}
                  context={context}
                  entry={entries.find((e) => e.task_id === task.id)}
                />
              ))}
              <label className="check">
                <input name="review-confirmed" type="checkbox" /> 저장할
                답변·처리 이유를 현재 원문과 직접 대조했습니다.
              </label>
              <div className="review-response-actions">
                {ai && (
                  <button type="submit" value="ai">
                    AI로 답변 확인·저장
                  </button>
                )}
                <button type="submit" value="manual" className="secondary">
                  직접 대조한 답변 저장
                </button>
              </div>
            </fieldset>
          </form>
        </>
      )}
    </section>
  );
}
