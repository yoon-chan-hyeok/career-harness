"use client";

import { useState } from "react";
import {
  recordedMessages,
  workroomRoles,
  type WorkroomRole,
} from "./workroom-state";
import type { Artifact } from "./workroom";

const labels: Record<string, string> = {
  RUNNING: "작업 중",
  DONE: "완료",
  READY: "준비됨",
  WAITING_USER: "확인 대기",
  STALE: "다시 검토",
  FAILED: "실패",
  NOT_STARTED: "요청 대기",
};
const basisLabels: Record<string, string> = {
  EXECUTION_RUN: "저장된 실행 기록",
  ARTIFACT: "저장된 문서",
  PROMPT_TRACE: "실제 AI 호출 기록",
  NO_ACTIVITY: "아직 작업 기록 없음",
};

// Original geometric pixel artwork. No external sprite or asset is embedded.
export function PixelAvatar({ roleKey }: { roleKey: string }) {
  const role =
    workroomRoles.find((entry) => entry.key === roleKey) || workroomRoles[0];
  return (
    <svg
      className="pixel-avatar"
      viewBox="0 0 24 28"
      aria-hidden="true"
      shapeRendering="crispEdges"
    >
      <path fill={role.hair} d="M7 2h10v2h3v10H4V4h3z" />
      <path fill="#e5bc98" d="M7 6h10v11H7zM5 9h2v5H5zm12 0h2v5h-2z" />
      <path fill={role.hair} d="M7 4h10v3H7zM7 7h2v2H7z" />
      <path fill="#423a34" d="M9 10h2v2H9zm5 0h2v2h-2z" />
      <path fill="#ac7059" d="M11 14h3v1h-3z" />
      <path fill={role.color} d="M5 18h14v8H5zM3 20h2v5H3zm16 0h2v5h-2z" />
      <path fill="#f7eee1" d="M10 18h4v4h-4z" />
      <path fill="#544940" d="M7 26h4v2H7zm6 0h4v2h-4z" />
    </svg>
  );
}

export function PixelOffice({
  roles,
  artifacts,
  onArtifact,
  motionAllowed,
  onMotionChange,
}: {
  roles: WorkroomRole[];
  artifacts: Artifact[];
  onArtifact: (artifact: Artifact) => void;
  motionAllowed: boolean;
  onMotionChange: (paused: boolean) => void;
}) {
  const [paused, setPaused] = useState(false);
  const [selectedKey, setSelectedKey] = useState("research");
  const messages = recordedMessages(roles);
  const selected = roles.find((role) => role.key === selectedKey);
  const selectedArtifact = artifacts.find(
    (artifact) => artifact.id === selected?.artifact_id,
  );
  return (
    <section
      className={`pixel-office ${paused || !motionAllowed ? "pixel-paused" : ""}`}
      aria-label="픽셀 에이전트 작업실"
    >
      <div className="pixel-office-header">
        <div>
          <span className="eyebrow">THE LITTLE WORKROOM</span>
          <h3>여섯 역할이 함께 만드는 다음 한 걸음</h3>
        </div>
        <button
          className="secondary pixel-motion-button"
          onClick={() => {
            setPaused(!paused);
            onMotionChange(!paused);
          }}
          aria-pressed={paused}
        >
          {paused ? "움직임 켜기" : "움직임 멈추기"}
        </button>
      </div>
      <div className="pixel-room-scene">
        <div className="pixel-room-decor" aria-hidden="true">
          <span className="pixel-window" />
          <span className="pixel-plant">✦</span>
          <span className="pixel-clock">◷</span>
        </div>
        <div className="pixel-desk-grid">
          {workroomRoles.map((role) => {
            const record = roles.find((entry) => entry.key === role.key);
            const running = record?.status === "RUNNING";
            return (
              <button
                key={role.key}
                className={`pixel-desk ${running ? "pixel-desk-working" : ""} ${selectedKey === role.key ? "pixel-desk-selected" : ""}`}
                onClick={() => setSelectedKey(role.key)}
                aria-pressed={selectedKey === role.key}
                aria-label={`${role.name} · ${labels[record?.status || "NOT_STARTED"] || "상태 확인 필요"}`}
              >
                <span className="pixel-desk-status">
                  {labels[record?.status || "NOT_STARTED"] || "상태 확인 필요"}
                </span>
                <span className="pixel-desk-art" aria-hidden="true">
                  <PixelAvatar roleKey={role.key} />
                  <span className="pixel-monitor">
                    <i className={running ? "pixel-monitor-active" : ""} />
                  </span>
                  <span className="pixel-table" />
                </span>
                <strong>{role.name}</strong>
              </button>
            );
          })}
        </div>
      </div>
      <div className="pixel-speech" aria-live="polite">
        <PixelAvatar roleKey={selectedKey} />
        <div>
          <strong>
            {workroomRoles.find((role) => role.key === selectedKey)?.name}
          </strong>
          <p>
            {selected?.message ||
              "아직 저장된 작업 기록이 없어요. 작업을 요청하면 이 자리에서 결과를 확인할 수 있어요."}
          </p>
          {selected?.basis && (
            <small>{basisLabels[selected.basis] || "서버 작업 기록"}</small>
          )}
          {selectedArtifact && (
            <button
              className="text-button"
              onClick={() => onArtifact(selectedArtifact)}
            >
              근거 문서 v{selectedArtifact.version} 열기 →
            </button>
          )}
        </div>
      </div>
      <div className="pixel-message-log">
        <div className="pixel-message-heading">
          <h3>역할별 작업 메시지</h3>
          <span>저장된 문서 · 실제 실행 기록</span>
        </div>
        {messages.length ? (
          <ol>
            {messages.map((message) => {
              const artifact = artifacts.find(
                (entry) => entry.id === message.artifact_id,
              );
              return (
                <li key={message.key}>
                  <PixelAvatar roleKey={message.key} />
                  <div>
                    <strong>{message.label}</strong>
                    <p>{message.message}</p>
                    <small>
                      {basisLabels[message.basis] || "서버 작업 기록"}
                    </small>
                    {message.updated_at && (
                      <time dateTime={message.updated_at}>
                        {new Date(message.updated_at).toLocaleString("ko-KR", {
                          timeZone: "Asia/Seoul",
                          month: "numeric",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                    )}
                    {message.provider && message.model && (
                      <small>
                        실행 기록: {message.provider} · {message.model}
                      </small>
                    )}
                    {artifact && (
                      <button
                        className="text-button"
                        onClick={() => onArtifact(artifact)}
                      >
                        저장 문서 v{artifact.version} →
                      </button>
                    )}
                    {message.trace_id && (
                      <details>
                        <summary>실행 식별자</summary>
                        <code>{message.trace_id}</code>
                      </details>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="pixel-log-empty">
            첫 작업 후 역할별 기록이 여기에 쌓입니다.
          </p>
        )}
      </div>
    </section>
  );
}
