"use client";
import {
  FormEvent,
  KeyboardEvent,
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { Artifact, Workspace } from "./workroom";
import { AssessmentDecision, RevisionInbox } from "./review-controls";
import { AgentWorkspace } from "./agent-workspace";
import { CorrectionInbox } from "./correction-controls";
import { ExperienceOptions } from "./experience-options";
import { ApplicationPacket } from "./application-packet";
import { ResearchStatus } from "./research-status";
import { WritingPlanPanel } from "./writing-plan-panel";
import { JointPortfolioPanel } from "./joint-portfolio-panel";

type Turn = {
  id: string;
  data: {
    request: { text: string };
    response: {
      text: string;
      artifact_ids: string[];
      status: string;
      question_id?: string;
      context_notice?: string;
    };
  };
};
type Request = (path: string, body?: unknown, method?: string) => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
const names: Record<string, string> = {
  OpportunityBrief: "직무 분석",
  OpportunityAssessment: "지원 가치·우선순위",
  CompanyResearchResult: "회사 조사",
  ResearchReview: "채용 배경 확인",
  ApprovedExpression: "승인한 표현",
  FinalSubmissionReview: "직업 정체성·마지막 세 질문",
  EvidencePack: "경험 연결",
  ApplicationBrief: "지원 전략",
  QuestionPortfolio: "문항별 역할",
  QuestionBrief: "문항 설계",
  WritingPlan: "작성 가이드·구성",
  ClaimEvidenceTest: "메시지 근거 검증",
  Draft: "자기소개서",
  ResumeBrief: "이력서 구성",
  ResumeContent: "이력서",
  Review: "문항 검수",
  ResumeReview: "이력서 검수",
  ReviewResponses: "문항 검수 답변",
  ResumeReviewResponses: "이력서 검수 답변",
  PortfolioReview: "전체 문서 검수",
  SubmissionBundle: "최종 보관본",
  InterviewHandoff: "면접 준비",
  Postmortem: "전형 회고",
};
const status = (value: string) =>
  value === "LOCKED"
    ? "승인·잠금"
    : value === "STALE" || value === "INVALID"
      ? "다시 검토"
      : value === "SUPERSEDED"
        ? "이전 버전"
        : "검토 중";

export function ConversationWorkspace({
  workspace: w,
  questionId,
  qSelect,
  evidenceOptions,
  sourceNames,
  request,
  send: sendRequest,
  refresh,
  onEdit,
  onBack,
  renderArtifact,
  ai,
}: {
  workspace: Workspace;
  questionId: string;
  qSelect: (qid: string) => void;
  evidenceOptions: { id: string; title: string }[];
  sourceNames: Record<string, string>;
  request: Request;
  send: (path: string) => Promise<Response>;
  refresh: (id: string) => Promise<void>;
  onEdit: (stage: number, qid?: string) => void;
  onBack: () => void;
  renderArtifact: (a: Artifact) => ReactNode;
  ai: boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]),
    [text, setText] = useState(""),
    [sending, setSending] = useState(false),
    [error, setError] = useState(""),
    [selectedId, setSelectedId] = useState(""),
    [evidenceId, setEvidenceId] = useState(""),
    [storageOpen, setStorageOpen] = useState(false),
    [view, setView] = useState<"conversation" | "agents">("conversation");
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const writingPlanDirty = useRef(false);
  const jointPortfolioDirty = useRef(false);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  const load = useCallback(
    async () => setTurns(await request(`/applications/${w.id}/conversation`)),
    [request, w.id],
  );
  useEffect(() => {
    let active = true;
    request(`/applications/${w.id}/conversation`)
      .then((rows) => {
        if (active) setTurns(rows);
      })
      .catch(() => {
        if (active)
          setError("대화를 불러오지 못했습니다. 다시 불러오기를 눌러 주세요.");
      });
    return () => {
      active = false;
    };
  }, [request, w.id]);
  useEffect(() => {
    end.current?.scrollIntoView({
      block: "end",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [turns.length, sending]);
  const current = Object.values(
    w.artifacts.reduce<Record<string, Artifact>>((result, a) => {
      const key = a.kind + ":" + a.slot;
      if (!result[key] || result[key].version < a.version) result[key] = a;
      return result;
    }, {}),
  );
  const selected = w.artifacts.find((a) => a.id === selectedId);
  const editStage = selected?.kind.startsWith("Resume")
    ? 3
    : selected?.kind === "ApplicationBrief"
      ? 1
      : [
            "SubmissionBundle",
            "PortfolioReview",
            "FinalSubmissionReview",
          ].includes(selected?.kind || "")
        ? 4
        : ["InterviewHandoff", "Postmortem"].includes(selected?.kind || "")
          ? 5
          : questionId
            ? 2
            : 0;
  const latest = (kind: string, slot = "") =>
    current.find((a) => a.kind === kind && a.slot === slot);
  const choose = (a?: Artifact, qid = "") => {
    setSelectedId(a?.id || "");
    qSelect(qid);
    setStorageOpen(true);
  };
  const send = async (message = text) => {
    if (!message.trim() || sending) return;
    if (writingPlanDirty.current || jointPortfolioDirty.current) {
      setError("변경한 작성 구성을 먼저 저장해 주세요.");
      return;
    }
    const body = {
      text: message.trim(),
      evidence_id: evidenceId,
      question_id: questionId,
      artifact_id: selected?.slot === questionId ? selected.id : "",
    };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature)
      pending.current = { signature, id: crypto.randomUUID() };
    setSending(true);
    setError("");
    try {
      const turn: Turn = await request(`/applications/${w.id}/conversation`, {
        ...body,
        client_id: pending.current.id,
      });
      setTurns((previous) =>
        previous.some((t) => t.id === turn.id) ? previous : [...previous, turn],
      );
      setText("");
      pending.current = null;
      await refresh(w.id);
      if (turn.data.response.question_id)
        qSelect(turn.data.response.question_id);
      const resultIds = turn.data.response.artifact_ids;
      if (resultIds.length) setSelectedId(resultIds[resultIds.length - 1]);
    } catch (e) {
      setError(
        e instanceof Error
          ? e.message
          : "메시지를 보내지 못했습니다. 다시 시도해 주세요.",
      );
    } finally {
      setSending(false);
      input.current?.focus();
    }
  };
  const submit = (event: FormEvent) => {
    event.preventDefault();
    void send();
  };
  const keyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (
      event.key === "Enter" &&
      !event.shiftKey &&
      !event.nativeEvent.isComposing
    ) {
      event.preventDefault();
      void send();
    }
  };
  const groups = [
    {
      title: "지원 준비",
      items: current.filter((a) =>
        [
          "OpportunityBrief",
          "OpportunityAssessment",
          "CompanyResearchResult",
          "EvidencePack",
          "ApplicationBrief",
          "QuestionPortfolio",
        ].includes(a.kind),
      ),
    },
    {
      title: "이력서 · 검수",
      items: current.filter((a) =>
        [
          "ResumeBrief",
          "ResumeContent",
          "ResumeReview",
          "Review",
          "ReviewResponses",
          "ResumeReviewResponses",
          "PortfolioReview",
          "FinalSubmissionReview",
          "ClaimEvidenceTest",
        ].includes(a.kind),
      ),
    },
    {
      title: "최종본 · 면접",
      items: current.filter((a) =>
        ["SubmissionBundle", "InterviewHandoff", "Postmortem"].includes(a.kind),
      ),
    },
  ];
  return (
    <div className="conversation-layout">
      <div className="chat-column">
        <div className="chat-toolbar">
          <button className="text-button" onClick={onBack}>
            ← 지원 목록
          </button>
          <div
            className="workspace-view-switch"
            role="tablist"
            aria-label="지원 준비 보기"
          >
            <button
              role="tab"
              id="conversation-view-tab"
              aria-controls="conversation-view-panel"
              aria-selected={view === "conversation"}
              onClick={() => setView("conversation")}
            >
              대화
            </button>
            <button
              role="tab"
              id="agent-view-tab"
              aria-controls="agent-view-panel"
              aria-selected={view === "agents"}
              onClick={() => setView("agents")}
            >
              <span aria-hidden="true">◇</span> 에이전트 작업
            </button>
          </div>
          <button
            className="storage-toggle secondary"
            onClick={() => setStorageOpen(!storageOpen)}
          >
            문서 보관함
          </button>
        </div>
        {view === "agents" ? (
          <div
            className="agent-view-panel"
            id="agent-view-panel"
            role="tabpanel"
            aria-labelledby="agent-view-tab"
          >
            <AgentWorkspace
              workspace={w}
              request={request}
              busy={sending}
              onArtifact={(artifact) => choose(artifact, artifact.slot)}
              onEdit={onEdit}
              onConversation={() => setView("conversation")}
            />
          </div>
        ) : (
          <div
            className="chat-messages"
            id="conversation-view-panel"
            role="tabpanel"
            aria-labelledby="conversation-view-tab"
            aria-label="지원 준비 대화"
            aria-live="polite"
          >
            {(!latest("OpportunityBrief") ||
              latest("CompanyResearchResult")?.data.scope) && (
              <ResearchStatus
                research={latest("CompanyResearchResult")}
                review={latest("ResearchReview")}
                onOpen={() => onEdit(0)}
              />
            )}
            {!turns.length && (
              <div className="chat-welcome">
                <span className="welcome-mark">h</span>
                <h2>어떤 이야기를 준비할까요?</h2>
                <p>
                  {w.company}의 {w.role} 지원을 함께 정리해요.
                  <br />
                  문항을 추가하거나, 오른쪽에 저장된 문서를 선택하세요.
                </p>
                <div className="suggestions">
                  <button onClick={() => void send("현재 상태")}>
                    어디까지 준비했지? ↗
                  </button>
                  <button
                    onClick={() => {
                      setText("문항 추가: ");
                      input.current?.focus();
                    }}
                  >
                    작성할 문항 추가 ↗
                  </button>
                  <button onClick={() => onEdit(0)}>
                    공고와 내 경험 연결 ↗
                  </button>
                </div>
              </div>
            )}
            {turns.map((turn) => (
              <div className="conversation-turn" key={turn.id}>
                <div className="user-message">
                  <span className="sr-only">나</span>
                  {turn.data.request.text}
                </div>
                <div className="assistant-message">
                  <span className="assistant-avatar" aria-hidden="true">
                    h
                  </span>
                  <div>
                    <strong>Career Harness</strong>
                    <p>{turn.data.response.text}</p>
                    {turn.data.response.context_notice && (
                      <small className="muted">
                        {turn.data.response.context_notice}
                      </small>
                    )}
                    {turn.data.response.artifact_ids.map((id) => {
                      const a = w.artifacts.find((item) => item.id === id);
                      return (
                        a && (
                          <button
                            className="message-artifact"
                            key={id}
                            onClick={() => choose(a, a.slot)}
                          >
                            <span>▤</span>
                            {names[a.kind] || "저장 문서"}
                            <small>
                              v{a.version} · {status(a.status)}
                            </small>
                            ↗
                          </button>
                        )
                      );
                    })}
                  </div>
                </div>
              </div>
            ))}
            {w.data.questions.length > 0 && (
              <JointPortfolioPanel
                key={`joint:${w.id}`}
                workspaceId={w.id}
                revisionKey={w.artifacts.map((a) => a.id + a.status).join(":")}
                request={request}
                onSaved={() => refresh(w.id)}
                ai={ai}
                disabled={sending}
                dirtyState={jointPortfolioDirty}
              />
            )}
            {questionId && (
              <WritingPlanPanel
                dirtyState={writingPlanDirty}
                key={`plan:${w.id}:${questionId}`}
                workspaceId={w.id}
                questionId={questionId}
                revisionKey={w.artifacts.map((a) => a.id + a.status).join(":")}
                request={request}
                onSaved={() => refresh(w.id)}
                designing={sending}
                onExperience={() => onEdit(2, questionId)}
                onDesign={
                  ai
                    ? async () => {
                        setSending(true);
                        try {
                          await request(
                            `/applications/${w.id}/actions/question-brief`,
                            { qid: questionId },
                          );
                          await refresh(w.id);
                        } finally {
                          setSending(false);
                        }
                      }
                    : undefined
                }
              />
            )}
            {sending && (
              <div className="assistant-message processing" role="status">
                <span className="assistant-avatar">h</span>자료와 현재 작업을
                확인하고 있어요…
              </div>
            )}
            <RevisionInbox
              workspace={w}
              request={request}
              refresh={() => refresh(w.id)}
              reloadKey={turns.length}
            />
            <CorrectionInbox
              workspace={w}
              request={request}
              refresh={() => refresh(w.id)}
            />
            <div ref={end} />
          </div>
        )}
        <div
          className={`composer-area${view === "agents" ? " agent-composer" : ""}`}
        >
          {error && (
            <div role="alert" className="error">
              {error}
              <button
                className="secondary"
                onClick={() =>
                  void load()
                    .then(() => setError(""))
                    .catch(() => setError("대화를 다시 불러오지 못했습니다."))
                }
              >
                다시 불러오기
              </button>
            </div>
          )}
          {questionId && (
            <div className="composer-context">
              선택 문항 ·{" "}
              {w.data.questions.find((q) => q.id === questionId)?.text}
              <button
                onClick={() => {
                  qSelect("");
                  setSelectedId("");
                }}
              >
                선택 해제
              </button>
            </div>
          )}
          <form onSubmit={submit} className="chat-composer">
            <textarea
              ref={input}
              aria-label="대화 메시지"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={keyDown}
              placeholder={
                questionId
                  ? "이 문항을 어떻게 다듬을까요?"
                  : "지원 준비에 대해 이야기해 보세요"
              }
              rows={2}
            />
            <div className="composer-bottom">
              <button
                type="button"
                className="composer-tool"
                onClick={() => onEdit(questionId ? 2 : 0, questionId)}
              >
                ＋ 직접 편집
              </button>
              <select
                className="composer-evidence"
                aria-label="대화 대상 경험"
                value={evidenceId}
                onChange={(e) => setEvidenceId(e.target.value)}
              >
                <option value="">경험 선택</option>
                {evidenceOptions.map((e) => (
                  <option key={e.id} value={e.id}>
                    {e.title}
                  </option>
                ))}
              </select>
              <button
                className="send-button"
                type="submit"
                disabled={sending || !text.trim()}
                aria-label="메시지 보내기"
              >
                ↑
              </button>
            </div>
          </form>
          <p className="composer-caption">
            Enter로 보내기 · Shift+Enter로 줄바꿈 · 작성 내용은 근거와 함께
            검토하세요.
          </p>
        </div>
      </div>
      <div
        className={`document-storage ${storageOpen ? "storage-visible" : ""}`}
      >
        <div className="storage-header">
          <div>
            <span className="eyebrow">YOUR WORK, SAVED</span>
            <h2>문서 보관함</h2>
          </div>
          <button
            className="storage-close"
            aria-label="보관함 닫기"
            onClick={() => setStorageOpen(false)}
          >
            ×
          </button>
        </div>
        <p className="storage-description">
          작성한 문항과 문서가 여기에 쌓입니다.
        </p>
        <div className="storage-scroll">
          <ApplicationPacket
            workspaceId={w.id}
            version={
              w.state + w.artifacts.map((a) => a.id + a.status).join(":")
            }
            request={request}
            send={sendRequest}
            onEdit={onEdit}
          />
          <ExperienceOptions
            ready={[latest("OpportunityBrief"), latest("EvidencePack")].every(
              (artifact) =>
                artifact && ["ACTIVE", "LOCKED"].includes(artifact.status),
            )}
            key={`${w.id}:${questionId || (selected?.kind.startsWith("Resume") ? "resume" : "strategy")}`}
            workspaceId={w.id}
            slot={
              questionId ||
              (selected?.kind.startsWith("Resume") ? "resume" : "strategy")
            }
            version={w.artifacts
              .map((artifact) => artifact.id + artifact.status)
              .join(":")}
            request={request}
            sourceNames={sourceNames}
            slotNames={Object.fromEntries(
              w.data.questions.map((question, index) => [
                question.id,
                `${index + 1}번 · ${question.text}`,
              ]),
            )}
            onSelected={async (id) => {
              setEvidenceId(id);
              await refresh(w.id);
            }}
          />
          <div className="storage-group">
            <div className="storage-group-heading">
              <h3>
                자기소개서 문항 <span>{w.data.questions.length}</span>
              </h3>
              <button aria-label="문항 추가" onClick={() => onEdit(2)}>
                ＋
              </button>
            </div>
            {w.data.questions.length ? (
              w.data.questions.map((q, i) => {
                const a =
                  latest("Draft", q.id) || latest("QuestionBrief", q.id);
                return (
                  <button
                    className={`stored-question ${questionId === q.id ? "active" : ""}`}
                    key={q.id}
                    onClick={() => choose(a, q.id)}
                  >
                    <span className="document-icon">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <span>
                      <strong>{q.text}</strong>
                      <small>
                        {q.limit.toLocaleString()}자 ·{" "}
                        {a ? status(a.status) : "작성 전"}
                      </small>
                    </span>
                    {a && <span className="saved-dot" />}
                  </button>
                );
              })
            ) : (
              <div className="storage-empty">
                <span>▤</span>
                <p>아직 저장한 문항이 없어요.</p>
                <button onClick={() => onEdit(2)}>첫 문항 추가하기</button>
              </div>
            )}
          </div>
          {groups.map((group) => (
            <div className="storage-group" key={group.title}>
              <h3>{group.title}</h3>
              {group.items.length ? (
                group.items.map((a) => (
                  <button
                    className={`stored-document ${selectedId === a.id ? "active" : ""}`}
                    key={a.id}
                    onClick={() => choose(a, a.slot)}
                  >
                    <span className="document-icon">▤</span>
                    <span>
                      <strong>{names[a.kind] || a.kind}</strong>
                      <small>
                        v{a.version} · {status(a.status)}
                      </small>
                    </span>
                  </button>
                ))
              ) : (
                <p className="storage-placeholder">
                  작업을 진행하면 문서가 저장됩니다.
                </p>
              )}
            </div>
          ))}
          {(selected || questionId) && (
            <div className="storage-preview">
              <div className="storage-group-heading">
                <h3>선택한 문서</h3>
                <button onClick={() => onEdit(editStage, questionId)}>
                  직접 편집
                </button>
              </div>
              {selected ? (
                renderArtifact(selected)
              ) : (
                <p className="muted">
                  아직 본문이 없습니다. 문항 메시지부터 정리하세요.
                </p>
              )}
              {selected?.kind === "OpportunityAssessment" && (
                <AssessmentDecision
                  key={selected.id}
                  artifact={selected}
                  workspace={w.id}
                  request={request}
                  refresh={() => refresh(w.id)}
                />
              )}
              <div className="chat-quick-actions">
                {selected &&
                  [
                    "Review",
                    "ResumeReview",
                    "ReviewResponses",
                    "ResumeReviewResponses",
                  ].includes(selected.kind) && (
                    <button
                      className="secondary"
                      onClick={() =>
                        onEdit(
                          selected.kind.startsWith("Resume") ? 3 : 2,
                          selected.slot,
                        )
                      }
                    >
                      검수 질문에 답변하기
                    </button>
                  )}
                {ai && (
                  <button disabled={sending} onClick={() => void send("ㄱㄱ")}>
                    다음 작업 진행
                  </button>
                )}
                {ai && w.data.questions.length > 1 && (
                  <button
                    className="secondary"
                    disabled={sending}
                    onClick={() => {
                      setSending(true);
                      void request(
                        `/applications/${w.id}/actions/question-portfolio`,
                        {},
                      )
                        .then(() => refresh(w.id))
                        .catch((error) =>
                          setError(
                            error instanceof Error
                              ? error.message
                              : "역할을 나누지 못했습니다.",
                          ),
                        )
                        .finally(() => setSending(false));
                    }}
                  >
                    모든 문항 역할 나누기
                  </button>
                )}
                {selected?.status === "ACTIVE" &&
                  [
                    "ApplicationBrief",
                    "QuestionBrief",
                    "QuestionPortfolio",
                  ].includes(selected.kind) && (
                    <button
                      disabled={sending}
                      onClick={() => void send("이걸로 가자")}
                    >
                      읽고 승인
                    </button>
                  )}
                {questionId && latest("Review", questionId) && (
                  <button
                    className="secondary"
                    onClick={() =>
                      choose(latest("Review", questionId), questionId)
                    }
                  >
                    문항 검수 보기
                  </button>
                )}
              </div>
              {selected && (
                <details>
                  <summary>이전 버전 보기</summary>
                  {w.artifacts
                    .filter(
                      (a) =>
                        a.kind === selected.kind && a.slot === selected.slot,
                    )
                    .sort((a, b) => b.version - a.version)
                    .map((a) => (
                      <button
                        className="version-item"
                        key={a.id}
                        onClick={() => setSelectedId(a.id)}
                      >
                        v{a.version} · {status(a.status)}
                      </button>
                    ))}
                </details>
              )}
            </div>
          )}
        </div>
        <div className="storage-footer">
          <button className="secondary" onClick={() => onEdit(4)}>
            검수 · 최종본 보관 →
          </button>
          <button className="text-button" onClick={() => onEdit(5)}>
            면접 준비와 결과 기록 →
          </button>
        </div>
      </div>
    </div>
  );
}
