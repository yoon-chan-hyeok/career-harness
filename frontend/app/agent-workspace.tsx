"use client";

import { useEffect, useRef, useState } from "react";
import type { Artifact, Workspace } from "./page";

type Request = (
  path: string,
  body?: unknown,
  method?: string,
) => Promise<unknown>;
type StageStatus =
  | "READY"
  | "RUNNING"
  | "WAITING_USER"
  | "DONE"
  | "STALE"
  | "FAILED"
  | "NOT_STARTED";
type Run = {
  id: string;
  action: string;
  label: string;
  status: "RUNNING" | "COMPLETED" | "WAITING_USER" | "FAILED";
  started_at: string;
  finished_at: string | null;
  elapsed_ms: number | null;
  error_code?: string | null;
  message?: string | null;
};
type Stage = {
  key: string;
  label: string;
  status: StageStatus;
  artifact_id?: string | null;
  artifact_version?: number | null;
  detail: string;
};
type Activity = {
  workspace_id: string;
  workflow_state: string;
  provider: { ai_available: boolean; jev_enabled: boolean };
  active_run: Run | null;
  runs: Run[];
  stages: Stage[];
  pending_review_count: number;
};

const statusLabels: Record<StageStatus, string> = {
  READY: "다음 작업 준비",
  RUNNING: "실행 중",
  WAITING_USER: "내 확인 대기",
  DONE: "완료",
  STALE: "근거 재검토",
  FAILED: "실행 실패",
  NOT_STARTED: "시작 전",
};
const roles: Record<string, { name: string; initial: string; task: string }> = {
  research: {
    name: "리서처",
    initial: "R",
    task: "회사와 공고의 출처를 확인합니다.",
  },
  opportunity: {
    name: "직무 분석가",
    initial: "J",
    task: "실제 업무와 채용 조건을 해석합니다.",
  },
  evidence: {
    name: "근거 연결 담당",
    initial: "E",
    task: "내 경험을 업무 산출물에 연결합니다.",
  },
  strategy: {
    name: "지원 전략가",
    initial: "S",
    task: "강점과 공백을 바탕으로 방향을 정합니다.",
  },
  writing: {
    name: "문서 작성자",
    initial: "W",
    task: "승인한 전략과 근거로 문서를 씁니다.",
  },
  review: {
    name: "검수 담당",
    initial: "Q",
    task: "사실, 수행 범위와 문항의 설득력을 확인합니다.",
  },
};
const workflowLabels: Record<string, string> = {
  CREATED: "공고 등록",
  OPPORTUNITY_READY: "직무 분석 완료",
  EVIDENCE_READY: "근거 연결 완료",
  WAITING_STRATEGY_APPROVAL: "전략 승인 대기",
  STRATEGY_LOCKED: "전략 승인 완료",
  COMPOSING: "문항 설계·작성",
  REVIEWING: "검수 중",
  READY_TO_FREEZE: "최종본 검토",
  SUBMISSION_FROZEN: "최종본 보관 · 미제출",
  SUBMITTED: "제출 확인 완료",
  CLOSED: "추적 종료 · 기록 보관",
  NEED_USER_ACTION: "변경된 근거 확인 필요",
};

function dateLabel(value: string | null) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "시각 확인 필요"
    : date.toLocaleString("ko-KR", {
        timeZone: "Asia/Seoul",
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
        hour12: false,
      });
}

function durationLabel(milliseconds: number | null) {
  if (milliseconds === null || !Number.isFinite(milliseconds)) return "";
  if (milliseconds < 1000) return "1초 미만";
  const seconds = Math.max(0, Math.floor(milliseconds / 1000));
  return seconds < 60
    ? `${seconds}초`
    : `${Math.floor(seconds / 60)}분 ${seconds % 60}초`;
}

function ActiveRun({ run }: { run: Run }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [run.id]);
  const started = new Date(run.started_at).getTime();
  const elapsed = Number.isNaN(started) ? null : Math.max(0, now - started);
  return (
    <div className="agent-active-run" role="status">
      <span className="agent-running-mark" aria-hidden="true">
        <span />
      </span>
      <div>
        <small>현재 실행</small>
        <strong>{run.label}</strong>
        <p>{run.message || "요청한 작업을 처리하고 있습니다."}</p>
      </div>
      <span className="agent-elapsed">{durationLabel(elapsed)}</span>
    </div>
  );
}

export function AgentWorkspace({
  workspace,
  request,
  busy,
  onArtifact,
  onEdit,
  onConversation,
}: {
  workspace: Workspace;
  request: Request;
  busy: boolean;
  onArtifact: (artifact: Artifact) => void;
  onEdit: (stage: number, qid?: string) => void;
  onConversation: () => void;
}) {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const inFlight = useRef(false);
  const workspaceVersion = workspace.artifacts.map((a) => a.id).join(":");

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setActivity((previous) =>
      previous?.workspace_id === workspace.id ? previous : null,
    );
    const schedule = (delay: number) => {
      clearTimeout(timer);
      if (active) timer = setTimeout(() => void load(), delay);
    };
    const load = async () => {
      if (!active) return;
      if (document.visibilityState === "hidden" || inFlight.current) {
        schedule(2500);
        return;
      }
      inFlight.current = true;
      setLoading(true);
      let interval = busy ? 2500 : 15000;
      try {
        const result = (await request(
          `/applications/${workspace.id}/activity`,
        )) as Activity;
        if (result.workspace_id !== workspace.id)
          throw new Error("작업 상태를 확인하지 못했습니다.");
        if (active) {
          setActivity(result);
          setCheckedAt(new Date().toISOString());
          setError("");
          if (result.active_run) interval = 2500;
        }
      } catch (e) {
        if (active)
          setError(
            e instanceof Error ? e.message : "작업 상태를 불러오지 못했습니다.",
          );
      } finally {
        inFlight.current = false;
        if (active) {
          setLoading(false);
          schedule(interval);
        }
      }
    };
    const visible = () => {
      if (document.visibilityState === "visible") {
        clearTimeout(timer);
        void load();
      }
    };
    void load();
    document.addEventListener("visibilitychange", visible);
    return () => {
      active = false;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [
    request,
    workspace.id,
    workspace.state,
    workspaceVersion,
    busy,
    refreshKey,
  ]);

  const pendingStages = activity?.stages.filter(
    (stage) => stage.status === "WAITING_USER" || stage.status === "STALE",
  );
  const phaseFor = (key: string) =>
    key === "strategy" ? 1 : key === "writing" ? 2 : key === "review" ? 4 : 0;

  return (
    <div className="agent-workspace" aria-label="에이전트 작업 보기">
      <div className="agent-workspace-heading">
        <div>
          <span className="eyebrow">WORK IN MOTION</span>
          <h2>역할마다, 다음 할 일을 명확하게.</h2>
          <p>
            {workspace.company} · {workspace.role}
          </p>
        </div>
        <button
          className="agent-refresh secondary"
          disabled={loading}
          onClick={() => setRefreshKey((value) => value + 1)}
          aria-label="에이전트 작업 상태 새로고침"
        >
          {loading ? "확인 중" : "새로고침"}
        </button>
      </div>
      {error && (
        <div role="alert" className="agent-load-error">
          {error}
          {activity && " 마지막 확인 상태를 표시하고 있습니다."}
        </div>
      )}
      {!activity ? (
        <div className="agent-loading" role="status">
          {loading
            ? "저장된 작업과 실행 기록을 확인하고 있어요."
            : "다시 불러오면 작업 상태를 확인할 수 있습니다."}
        </div>
      ) : (
        <>
          <div className="agent-provider-row">
            <span className="agent-workflow-state">
              {workflowLabels[activity.workflow_state] || "작업 상태 확인 중"}
            </span>
            <span className={activity.provider.ai_available ? "connected" : ""}>
              <i aria-hidden="true" />
              AI {activity.provider.ai_available ? "설정됨" : "연결 대기"}
            </span>
            <span className={activity.provider.jev_enabled ? "connected" : ""}>
              <i aria-hidden="true" />Jev 보조 판단{" "}
              {activity.provider.jev_enabled ? "설정됨" : "연결 대기"}
            </span>
          </div>
          {activity.active_run && !error ? (
            <ActiveRun key={activity.active_run.id} run={activity.active_run} />
          ) : (
            <div className="agent-idle-run">
              <span className="agent-idle-mark" aria-hidden="true">
                h
              </span>
              <div>
                <strong>
                  {error
                    ? "실행 상태 연결 확인 필요"
                    : busy
                      ? "요청 확인 중"
                      : "다음 요청을 기다리고 있어요"}
                </strong>
                <p>
                  {error
                    ? "현재 실행 여부를 확인할 수 없습니다. 마지막 확인한 문서와 기록은 아래에서 읽을 수 있습니다."
                    : busy
                      ? "실행 기록이 등록되면 현재 작업을 여기에서 확인할 수 있습니다."
                      : "아래 대화창에서 작업을 요청하거나, 저장된 문서를 읽고 다음 단계를 결정하세요."}
                </p>
              </div>
            </div>
          )}
          {!!pendingStages?.length && (
            <div className="agent-attention">
              <span aria-hidden="true">↳</span>
              <div>
                <strong>내 확인이 필요한 작업</strong>
                <p>{pendingStages.map((stage) => stage.label).join(" · ")}</p>
              </div>
              <button className="text-button" onClick={onConversation}>
                대화에서 확인 →
              </button>
            </div>
          )}
          <div className="agent-stage-grid">
            {activity.stages.map((stage, index) => {
              const role = roles[stage.key] || {
                name: stage.label,
                initial: String(index + 1),
                task: "저장된 작업 상태를 확인합니다.",
              };
              const artifact = workspace.artifacts.find(
                (item) => item.id === stage.artifact_id,
              );
              return (
                <article
                  className={`agent-stage-card agent-stage-${stage.status.toLowerCase()}`}
                  key={stage.key}
                >
                  <div className="agent-stage-top">
                    <span className="agent-role-icon" aria-hidden="true">
                      {role.initial}
                    </span>
                    <span
                      className={`agent-status agent-status-${stage.status.toLowerCase()}`}
                    >
                      {statusLabels[stage.status] || "상태 확인 필요"}
                    </span>
                  </div>
                  <span className="agent-role-name">{role.name}</span>
                  <h3>{stage.label}</h3>
                  <p className="agent-role-task">{role.task}</p>
                  <p className="agent-stage-detail">{stage.detail}</p>
                  <div className="agent-stage-bottom">
                    {artifact ? (
                      <button
                        className="agent-document-button"
                        onClick={() => onArtifact(artifact)}
                      >
                        ▤ 저장 문서 <small>v{artifact.version}</small>{" "}
                        <span>↗</span>
                      </button>
                    ) : (
                      <span className="agent-no-document">저장 문서 대기</span>
                    )}
                    {(stage.status === "READY" ||
                      stage.status === "WAITING_USER" ||
                      stage.status === "STALE" ||
                      stage.status === "FAILED") && (
                      <button
                        className="agent-edit-button"
                        onClick={() =>
                          onEdit(phaseFor(stage.key), artifact?.slot)
                        }
                      >
                        {stage.status === "WAITING_USER"
                          ? "읽고 확인"
                          : stage.status === "STALE"
                            ? "다시 검토"
                            : "작업 열기"}{" "}
                        →
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
          {!!activity.pending_review_count && (
            <button className="agent-proposal-link" onClick={onConversation}>
              <span>
                수정안 {activity.pending_review_count}건이 확인을 기다립니다.
              </span>
              수정 전후 보기 →
            </button>
          )}
          <div className="agent-history">
            <div className="agent-history-heading">
              <h3>최근 실행 기록</h3>
              <span>
                {activity.runs.length
                  ? `${activity.runs.length}건`
                  : "기록 대기"}
              </span>
            </div>
            {activity.runs.length ? (
              <ol className="agent-run-list">
                {activity.runs.map((run) => (
                  <li key={run.id}>
                    <span
                      className={`agent-run-dot agent-run-${run.status.toLowerCase()}`}
                      aria-hidden="true"
                    />
                    <div className="agent-run-content">
                      <div className="agent-run-title">
                        <strong>{run.label}</strong>
                        <span>
                          {run.status === "COMPLETED"
                            ? "완료"
                            : run.status === "WAITING_USER"
                              ? "내 확인 대기"
                              : run.status === "FAILED"
                                ? "실패"
                                : "실행 중"}
                        </span>
                      </div>
                      {run.message && <p>{run.message}</p>}
                      <div className="agent-run-meta">
                        <time dateTime={run.started_at}>
                          {dateLabel(run.started_at)}
                        </time>
                        {run.finished_at && (
                          <span>
                            소요 {durationLabel(run.elapsed_ms) || "확인 필요"}
                          </span>
                        )}
                        {run.status === "FAILED" && run.error_code && (
                          <span>오류 {run.error_code}</span>
                        )}
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="agent-history-empty">
                첫 작업을 실행하면 처리 결과와 시간이 여기에 남습니다.
              </p>
            )}
          </div>
          <p className="agent-status-caption">
            역할별 상태는 저장된 문서와 서버 실행 기록을 기준으로 표시합니다.
            {checkedAt && <> · 확인 {dateLabel(checkedAt)}</>}
          </p>
        </>
      )}
    </div>
  );
}
