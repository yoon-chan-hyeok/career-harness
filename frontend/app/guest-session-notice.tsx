"use client";
import { useEffect, useState } from "react";
import type { Request } from "./api-client";
import { guestSessionInfo } from "./auth-client";
import { downloadPrivateExport } from "./private-export";

function remainingLabel(seconds: number) {
  const minutes = Math.ceil(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return hours
    ? `약 ${hours}시간${rest ? ` ${rest}분` : ""} 남음`
    : `약 ${minutes}분 남음`;
}

export function GuestSessionNotice({
  request,
  disabled = false,
}: {
  request: Request;
  disabled?: boolean;
}) {
  const [instant, setInstant] = useState(() => Date.now());
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    const sync = () => setInstant(Date.now());
    const timer = window.setInterval(sync, 30000);
    document.addEventListener("visibilitychange", sync);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", sync);
    };
  }, []);
  const session = guestSessionInfo(instant);
  if (!session) return null;
  const expired = session.remainingSeconds === 0;
  const endingSoon = session.remainingSeconds <= 3600;
  return (
    <section
      className={`guest-session-notice${endingSoon ? " guest-session-ending" : ""}`}
      aria-label="체험 연결과 자료 보관"
    >
      <div>
        <strong>
          체험 작업실 ·{" "}
          {expired ? "연결 종료" : remainingLabel(session.remainingSeconds)}
        </strong>
        <p>
          {expired
            ? "새 체험은 페이지를 새로고침해 시작하세요. 화면에 남은 필요한 문장은 먼저 보관해 주세요."
            : "탭 종료·로그아웃·만료 뒤에는 자료를 다시 찾을 수 없습니다. 필요한 자료를 미리 보관하세요."}
        </p>
        {endingSoon && !expired && (
          <p className="guest-session-reminder">
            체험 종료가 가까워졌습니다. 작성한 문서를 내려받아 주세요.
          </p>
        )}
        {message && <p role="status">{message}</p>}
        {error && (
          <p role="alert" className="guest-session-error">
            {error}
          </p>
        )}
      </div>
      <button
        className="secondary"
        disabled={disabled || saving || expired}
        onClick={async () => {
          setSaving(true);
          setMessage("");
          setError("");
          try {
            await downloadPrivateExport(request);
            setMessage(
              "전체 자료 파일 내려받기를 시작했습니다. 지원 문서는 보관함에서 PDF·Word로도 받을 수 있습니다.",
            );
          } catch (error) {
            setError(
              error instanceof Error
                ? error.message
                : "자료를 내려받지 못했습니다.",
            );
          } finally {
            setSaving(false);
          }
        }}
      >
        {saving ? "자료 준비 중…" : "내 자료 전체 내려받기"}
      </button>
    </section>
  );
}
