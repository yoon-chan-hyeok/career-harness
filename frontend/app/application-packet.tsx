"use client";

import { useEffect, useState } from "react";
import type { Request } from "./api-client";

type Check = {
  code: string;
  label: string;
  complete: boolean;
  stage: number;
  slot: string;
  detail: string;
};
type Packet = {
  basis: string;
  checklist: Check[];
  next_action: Check | null;
  download_available: boolean;
  frozen_at: string | null;
};

export function ApplicationPacket({
  workspaceId,
  version,
  request,
  send,
  onEdit,
}: {
  workspaceId: string;
  version: string;
  request: Request;
  send: (path: string) => Promise<Response>;
  onEdit: (stage: number, slot?: string) => void;
}) {
  const [packet, setPacket] = useState<Packet | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setError("");
    setPacket(null);
    request(`/applications/${workspaceId}/packet`)
      .then((data: Packet) => {
        if (active) setPacket(data);
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : "확인 목록을 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, [request, workspaceId, version, revision]);
  const download = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await send(
        `/applications/${workspaceId}/packet/download`,
      );
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = "지원서-최종-문서묶음.zip";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "문서 묶음을 받지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="packet-card" aria-label="제출 준비 확인">
      <div className="storage-group-heading">
        <h3>이 지원의 문서 묶음</h3>
        {packet && (
          <span>
            {packet.checklist.filter((item) => item.complete).length}/
            {packet.checklist.length}
          </span>
        )}
      </div>
      {packet ? (
        <>
          <p className="muted">
            {packet.basis === "FROZEN_SNAPSHOT"
              ? "보관한 최종 버전 기준"
              : "현재 작성 중인 버전 기준"}
          </p>
          <ul className="packet-checklist">
            {packet.checklist.map((item) => (
              <li key={item.code}>
                <button
                  className="packet-check"
                  onClick={() => onEdit(item.stage, item.slot)}
                  title={item.detail || undefined}
                >
                  <span aria-hidden="true">{item.complete ? "✓" : "○"}</span>
                  <span>
                    {item.label}
                    <small>{item.complete ? "확인됨" : "확인 필요"}</small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {packet.next_action && (
            <button
              className="secondary"
              onClick={() =>
                onEdit(packet.next_action!.stage, packet.next_action!.slot)
              }
            >
              다음: {packet.next_action.label}
            </button>
          )}
          {packet.download_available && (
            <button disabled={busy} onClick={() => void download()}>
              {busy ? "파일 준비 중…" : "최종 문서 묶음 받기"}
            </button>
          )}
          <small className="muted">
            실제 제출은 직접 확인한 뒤 완료로 기록합니다.
          </small>
        </>
      ) : (
        !error && <p role="status">문서 상태 확인 중…</p>
      )}
      {error && (
        <div role="alert">
          <p className="error">{error}</p>
          <button
            className="secondary"
            onClick={() => setRevision((value) => value + 1)}
          >
            다시 확인
          </button>
        </div>
      )}
    </section>
  );
}
