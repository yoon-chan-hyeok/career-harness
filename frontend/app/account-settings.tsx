"use client";
import { useEffect, useState } from "react";
import type { Request } from "./api-client";
import { clearSession } from "./auth-client";
import { EmailCodeForm } from "./email-code-form";
import type { PublicService } from "./public-service";

type Account = {
  status: "ACTIVE" | "CLOSED";
  can_export: boolean;
  can_delete: boolean;
  delete_unavailable_reason: string | null;
  deletion: {
    status: string;
    career_data_deleted: boolean;
    auth_account_deleted: boolean;
  };
  requires_recent_email_otp: boolean;
  reauthentication_max_age_seconds: number;
  notice: string;
};
const reasons: Record<string, string> = {
  OPERATOR_ACCOUNT: "운영자 계정은 이 화면에서 삭제할 수 없습니다.",
  SUPABASE_REQUIRED: "계정 삭제는 운영 로그인 연결 후 사용할 수 있습니다.",
  SERVER_DELETE_UNAVAILABLE:
    "현재 계정 삭제 연결을 준비 중입니다. 아래 문의처로 삭제를 요청해 주세요.",
};

export function AccountSettings({
  request,
  service,
  onDeleted,
}: {
  request: Request;
  service: PublicService;
  onDeleted: () => Promise<void>;
}) {
  const [account, setAccount] = useState<Account | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [reauthentication, setReauthentication] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  useEffect(() => {
    let active = true;
    request("/account")
      .then((value) => {
        if (active) setAccount(value);
      })
      .catch(() => {
        if (active)
          setError("계정 정보를 불러오지 못했습니다. 새로고침해 주세요.");
      });
    return () => {
      active = false;
    };
  }, [request]);
  const remove = async () => {
    if (busy || confirmation !== "DELETE" || !reauthentication) return;
    setBusy(true);
    setError("");
    try {
      const result = await request("/account/delete", {
        confirmation,
        reauthentication_token: reauthentication,
      });
      if (result.status !== "DELETED")
        throw new Error(
          "삭제 상태를 확인하지 못했습니다. 계정 상태를 확인한 뒤 다시 시도해 주세요.",
        );
      clearSession();
      setReauthentication("");
      setConfirmation("");
      await onDeleted();
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "삭제를 완료하지 못했습니다.",
      );
      try {
        const value: Account = await request("/account");
        setAccount(value);
        if (value.status === "CLOSED")
          setNotice(
            "작업실 접근이 중지되었고 계정 삭제를 처리 중입니다. 다시 시도하면 남은 삭제 절차를 이어서 진행합니다. 인증이 만료됐다면 이메일로 다시 본인 확인을 해 주세요.",
          );
      } catch {
        /* The page-level session handler also handles expired authentication. */
      }
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="account-settings">
      <h3>내 계정</h3>
      <p>계정 삭제 전 필요한 자료를 먼저 보관하세요.</p>
      {account?.can_export && (
        <button
          className="secondary"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setError("");
            try {
              const data = await request("/export");
              const url = URL.createObjectURL(
                new Blob([JSON.stringify(data, null, 2)], {
                  type: "application/json",
                }),
              );
              const link = document.createElement("a");
              link.href = url;
              link.download = "career-private-export.json";
              link.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            } catch (error) {
              setError(
                error instanceof Error
                  ? error.message
                  : "내려받기를 완료하지 못했습니다.",
              );
            } finally {
              setBusy(false);
            }
          }}
        >
          내 자료 전체 내려받기
        </button>
      )}
      {account?.notice && <p className="muted">{account.notice}</p>}
      {account && !account.can_delete && (
        <p role="status">
          {reasons[account.delete_unavailable_reason || ""] ||
            "현재 계정을 삭제할 수 없습니다."}
        </p>
      )}
      {service.support_email && (
        <p>
          문의:{" "}
          <a href={"mailto:" + service.support_email}>
            {service.support_email}
          </a>
        </p>
      )}
      {account?.can_delete && (
        <button
          className="secondary"
          onClick={() => {
            setExpanded(!expanded);
            setReauthentication("");
            setConfirmation("");
          }}
        >
          계정 삭제 {expanded ? "닫기" : "안내"}
        </button>
      )}
      {expanded && (
        <div className="account-delete-panel">
          <h4>계정과 지원 자료 삭제</h4>
          <p>
            경험·지원 문서·대화·제출 보관본을 삭제하고 작업실 접근을 중지합니다.
            되돌릴 수 없으며, 운영용 최소 접근 차단 기록과 사용량·삭제 처리
            기록은 남습니다. 백업 보관과 삭제 기준은 개인정보 처리방침에서
            확인할 수 있습니다.
          </p>
          <p>
            현재 로그인한 이메일로 본인 확인을 다시 진행해 주세요. 인증 후 5분
            안에 삭제를 확정해야 합니다.
          </p>
          {!reauthentication ? (
            <EmailCodeForm
              siteKey={service.captcha_site_key}
              createUser={false}
              reauthenticate
              onVerified={async (token) => {
                setReauthentication(token);
                setError("");
              }}
            />
          ) : (
            <>
              <p role="status">이메일 본인 확인을 마쳤습니다.</p>
              <label>
                삭제를 확정하려면 DELETE를 입력하세요.
                <input
                  autoComplete="off"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                />
              </label>
              <div className="public-actions">
                <button
                  disabled={busy || confirmation !== "DELETE"}
                  onClick={() => void remove()}
                >
                  {busy ? "삭제 처리 중…" : "계정과 내 자료 삭제"}
                </button>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => {
                    setReauthentication("");
                    setConfirmation("");
                  }}
                >
                  본인 확인 다시 하기
                </button>
              </div>
            </>
          )}
        </div>
      )}
      {notice && (
        <p role="status" className="note">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
