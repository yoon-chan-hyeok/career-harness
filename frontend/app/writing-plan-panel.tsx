"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Request } from "./api-client";

type Guide = {
  label: string;
  origin: string;
  question_intent: string;
  allocation: {
    order: number;
    content: string;
    approximate_characters: number;
    what_to_write: string;
  }[];
  writing_strategy: { instruction: string }[];
  reference_example: {
    origin: string;
    notice?: string;
    total_characters?: number;
    body_paragraph_count?: number;
    paragraphs: { kind: string; function: string; text: string }[];
  };
  source: { source_url: string; source_quote?: string } | null;
  skill_rules: string[];
};
type Plan = {
  workspace_id: string;
  question_id: string;
  question: { text: string; limit: number };
  guide: Guide;
  guide_snapshot_sha256: string;
  state_revision: string;
  plan: { id: string; version: number; status: string } | null;
  plan_current: boolean;
  emphasis: { state: "active" | "unused" | "discarded"; text: string };
  working_notes: string;
  selected_evidence: { id: string; title: string }[];
  missing_information: string[];
  phase: string;
  counting_notice: string;
  can_design: boolean;
};
const phases: Record<string, string> = {
  PLANNING: "작성 설계 중",
  MESSAGE: "메시지·근거 확인 중",
  READY: "초안 작성 준비",
  REVIEW: "초안 검수·수정 중",
  COMPLETED: "문항 완성",
};
const exampleLabel = (guide: Guide) =>
  guide.reference_example.origin === "WITHHELD_RIGHTS_PENDING"
    ? "예시 공개 범위 안내"
    : guide.origin === "ARCHIVED_REFERENCE"
    ? "출처에 수록된 참고 예시"
    : "내용을 채우는 구조 예시";

export function WritingPlanPanel({
  workspaceId,
  questionId,
  revisionKey,
  request,
  onSaved,
  onDesign,
  onExperience,
  designing = false,
  dirtyState,
}: {
  workspaceId: string;
  questionId: string;
  revisionKey: string;
  request: Request;
  onSaved: () => Promise<void>;
  onDesign?: () => Promise<void>;
  onExperience?: () => void;
  designing?: boolean;
  dirtyState?: { current: boolean };
}) {
  const [data, setData] = useState<Plan | null>(null);
  const [mode, setMode] = useState<Plan["emphasis"]["state"]>("unused");
  const [emphasis, setEmphasis] = useState("");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reload, setReload] = useState(0);
  const dirty = useRef(false);
  useEffect(
    () => () => {
      if (dirtyState) dirtyState.current = false;
    },
    [dirtyState],
  );
  const path =
    "/applications/" +
    workspaceId +
    "/questions/" +
    encodeURIComponent(questionId) +
    "/writing-plan";
  const load = useCallback(
    () => request(path) as Promise<Plan>,
    [request, path],
  );

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    load()
      .then((next) => {
        if (!active) return;
        if (
          next.workspace_id !== workspaceId ||
          next.question_id !== questionId
        )
          throw new Error("작업 문항이 바뀌었습니다. 다시 불러와 주세요.");
        setData(next);
        if (!dirty.current || next.emphasis.state === "discarded") {
          setMode(next.emphasis.state);
          setEmphasis(next.emphasis.text);
          setNotes(next.working_notes);
        }
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : "작성 설계를 불러오지 못했습니다.",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [load, workspaceId, questionId, revisionKey, reload]);

  async function save(andDesign = false) {
    if (!data || saving || designing) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await request(path, {
        expected_revision: data.state_revision,
        emphasis_state: mode,
        emphasis,
        working_notes: notes,
      });
      dirty.current = false;
      if (dirtyState) dirtyState.current = false;
      await onSaved();
      const next = await load();
      setData(next);
      setMode(next.emphasis.state);
      setEmphasis(next.emphasis.text);
      setNotes(next.working_notes);
      setNotice(
        "작성 구성을 저장했습니다. 같은 가이드와 선택 내용을 문항 설계·초안에 사용합니다.",
      );
      if (andDesign && onDesign) await onDesign();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "작성 구성을 저장하지 못했습니다.",
      );
    } finally {
      setSaving(false);
    }
  }
  const edit = () => {
    dirty.current = true;
    if (dirtyState) dirtyState.current = true;
    setNotice("변경한 구성은 저장한 뒤 문항 설계·초안에 반영됩니다.");
  };
  const disabled =
    saving || designing || loading || data?.phase === "COMPLETED";
  const source = data?.guide.source;
  const sourceUrl = source?.source_url.startsWith("https://")
    ? source.source_url
    : undefined;

  return (
    <section className="writing-plan" aria-label="초안 전 작성 설계">
      <div className="writing-plan-heading">
        <div>
          <span className="eyebrow">초안 전에 함께 설계하기</span>
          <h3>이 문항은 이렇게 써볼까요?</h3>
        </div>
        <button
          type="button"
          className="text-button"
          onClick={() => setReload((n) => n + 1)}
          disabled={saving || loading}
          aria-label="작성 설계 새로고침"
        >
          ↻
        </button>
      </div>
      {loading && (
        <p role="status" className="muted">
          문항에 맞는 가이드를 확인하고 있어요…
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {data && (
        <>
          <div className="writing-plan-meta">
            <span className="writing-plan-badge">
              {phases[data.phase] || "작성 설계"}
            </span>
            <span>
              {data.question.limit.toLocaleString()}자 · {data.guide.label}
            </span>
            {data.plan && (
              <span>
                저장 v{data.plan.version}
                {!data.plan_current ? " · 다시 확인" : ""}
              </span>
            )}
          </div>
          <p className="writing-plan-question">{data.question.text}</p>
          <p className="writing-plan-intent">{data.guide.question_intent}</p>
          <ol className="writing-plan-steps" aria-label="문항 완성 순서">
            {[
              "구성 이해",
              "경험 연결",
              "메시지·근거 확인",
              "초안",
              "검수·완성",
            ].map((step) => (
              <li key={step}>{step}</li>
            ))}
          </ol>
          <h4>무엇에 얼마나 쓸까요?</h4>
          <p className="muted">
            내용별 권장 분량입니다. 경험에 맞게 조정하며, 아래 구간을 같은 수의
            문단으로 나눌 필요는 없어요.
          </p>
          <ol className="writing-plan-allocation">
            {data.guide.allocation.map((part) => (
              <li key={part.order}>
                <div>
                  <strong>{part.content}</strong>
                  <p>{part.what_to_write}</p>
                </div>
                <span>약 {part.approximate_characters.toLocaleString()}자</span>
              </li>
            ))}
          </ol>
          <details className="writing-plan-details">
            <summary>작성 전략과 {exampleLabel(data.guide)} 보기</summary>
            <ul>
              {data.guide.writing_strategy.map((item, index) => (
                <li key={index}>{item.instruction}</li>
              ))}
            </ul>
            <div className="writing-plan-example">
              <strong>{exampleLabel(data.guide)}</strong>
              {data.guide.reference_example.notice && (
                <p>{data.guide.reference_example.notice}</p>
              )}
              {data.guide.reference_example.total_characters && (
                <small>
                  원문 실측 {data.guide.reference_example.total_characters}자 ·
                  본문 {data.guide.reference_example.body_paragraph_count}문단
                </small>
              )}
              {data.guide.reference_example.paragraphs.map(
                (paragraph, index) => (
                  <div key={index}>
                    <span className="writing-plan-function">
                      {paragraph.function}
                    </span>
                    <p
                      className={
                        paragraph.kind === "title"
                          ? "writing-plan-example-title"
                          : ""
                      }
                    >
                      {paragraph.text}
                    </p>
                  </div>
                ),
              )}
            </div>
            <p className="muted">
              예시는 구성 참고입니다. 예시의 프로젝트·기관·성과 수치는 본인의
              경험으로 사용하지 않아요.
            </p>
            {source && (
              <div className="writing-plan-source">
                {sourceUrl && (
                  <a href={sourceUrl} target="_blank" rel="noreferrer">
                    가이드 원문 출처 ↗
                  </a>
                )}
                {source.source_quote && <blockquote>{source.source_quote}</blockquote>}
                <small>
                  보관된 참고 자료이며 현재 채용 조건을 증명하지 않습니다.
                </small>
              </div>
            )}
            <ul>
              {data.guide.skill_rules.map((rule) => (
                <li key={rule}>{rule}</li>
              ))}
            </ul>
          </details>
          <div className="writing-plan-evidence">
            <h4>내 경험으로 연결하기</h4>
            {data.selected_evidence.length ? (
              <ul>
                {data.selected_evidence.map((item) => (
                  <li key={item.id}>{item.title}</li>
                ))}
              </ul>
            ) : (
              <p>아직 이 문항에 쓸 경험을 선택하지 않았어요.</p>
            )}
            {onExperience && (
              <button
                type="button"
                className="secondary"
                onClick={onExperience}
              >
                경험 선택·정보 보완
              </button>
            )}
            {!!data.missing_information.length && (
              <details open>
                <summary>작성 전에 확인할 내용</summary>
                <ul>
                  {data.missing_information.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void save();
            }}
            className="writing-plan-form"
          >
            <label>
              강조 방향 <span className="muted">(선택)</span>
              <select
                aria-label="강조 방향 사용 상태"
                value={mode}
                disabled={disabled || data.emphasis.state === "discarded"}
                onChange={(event) => {
                  edit();
                  const next = event.target.value as Plan["emphasis"]["state"];
                  setMode(next);
                  if (next === "discarded") setEmphasis("");
                }}
              >
                <option value="unused">사용 안 함</option>
                <option value="active">사용</option>
                <option value="discarded">폐기</option>
              </select>
            </label>
            {mode !== "discarded" && (
              <label>
                어떤 점을 강조하고 싶나요?
                <textarea
                  aria-label="문항의 강조 방향"
                  maxLength={400}
                  rows={2}
                  value={emphasis}
                  disabled={disabled}
                  onChange={(event) => {
                    edit();
                    setEmphasis(event.target.value);
                  }}
                  placeholder="예: 방법을 바꾸게 된 판단을 먼저 보여주고 싶어요."
                />
              </label>
            )}
            {mode === "discarded" && (
              <p className="muted">
                폐기 상태로 저장하면 강조 내용이 제거되고 생성에 포함되지
                않습니다.
              </p>
            )}
            <label>
              이 문항을 위한 작성 메모
              <textarea
                aria-label="문항 작성 메모"
                maxLength={4000}
                rows={3}
                value={notes}
                disabled={disabled}
                onChange={(event) => {
                  edit();
                  setNotes(event.target.value);
                }}
                placeholder="어떤 장면을 다루고 싶은지, 더 확인해야 할 내용을 적어두세요."
              />
            </label>
            <p className="muted">
              메모는 작성 참고입니다. 새 경력·성과는 경험 정리에서 근거를
              등록하고 확인해 주세요.
            </p>
            <div className="writing-plan-actions">
              <button
                disabled={disabled || (mode === "active" && !emphasis.trim())}
              >
                {saving ? "저장 중…" : "작성 구성 저장"}
              </button>
              {onDesign && (
                <button
                  type="button"
                  className="secondary"
                  disabled={
                    disabled ||
                    !data.can_design ||
                    (mode === "active" && !emphasis.trim())
                  }
                  onClick={() => void save(true)}
                >
                  다음: 핵심 메시지 설계
                </button>
              )}
            </div>
            {notice && <p role="status">{notice}</p>}
          </form>
          <p className="muted writing-plan-counter">{data.counting_notice}</p>
        </>
      )}
    </section>
  );
}
