"use client";

import { useEffect, useState } from "react";
import { ApiError, type Request } from "./api-client";
import { safeRepositoryUrl } from "./workroom-state";

type Total = {
  calls: number;
  tokens: number;
  reserved_calls: number;
  reserved_tokens: number;
  remaining_calls: number;
  estimated_cost_usd: number | null;
};
type AdminStatus = {
  is_admin: true;
  scope: "CURRENT_ACCOUNT";
  environment: string;
  authentication_mode: string;
  database: { status: string; dialect: string };
  counts: {
    applications: number;
    sources: number;
    evidence: number;
    artifacts: number;
    pending_approvals: number;
    stale_artifacts: number;
    failed_executions: number;
  };
  recent_executions: {
    id: string;
    workspace_id: string;
    action: string;
    label: string;
    status: string;
    started_at: string;
    finished_at: string | null;
    elapsed_ms: number | null;
    error_code: string | null;
  }[];
  usage: { daily: Total; monthly: Total; timezone: string; notice: string };
  provider: { configured: boolean; live_verified: boolean };
  connections: { key: string; label: string; status: string; detail: string }[];
  source_repository_url: string | null;
  notice: string;
};
const countLabels: Record<keyof AdminStatus["counts"], string> = {
  applications: "지원 작업",
  sources: "원자료",
  evidence: "경험 근거",
  artifacts: "저장 문서",
  pending_approvals: "승인 대기",
  stale_artifacts: "다시 검토",
  failed_executions: "실패 기록",
};
const stateLabels: Record<string, string> = {
  COMPLETED: "완료",
  RUNNING: "실행 중",
  WAITING_USER: "확인 대기",
  FAILED: "실패",
  READY: "준비됨",
  CONFIGURED: "설정됨",
  VERIFIED: "확인됨",
  NOT_CONFIGURED: "연결 전",
  MISSING: "연결 전",
  DISABLED: "사용 안 함",
  UNVERIFIED: "실행 확인 전",
  AVAILABLE: "응답 정상",
  ok: "응답 정상",
};

export function AdminConsole({
  request,
  onSettings,
}: {
  request: Request;
  onSettings: () => void;
}) {
  const [data, setData] = useState<AdminStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [denied, setDenied] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    let active = true;
    setData(null);
    setLoading(true);
    setError("");
    setDenied(false);
    request("/admin/status")
      .then((result: AdminStatus) => {
        if (!result.is_admin || result.scope !== "CURRENT_ACCOUNT")
          throw new Error("관리자 응답을 확인하지 못했습니다.");
        if (active) setData(result);
      })
      .catch((reason) => {
        if (!active) return;
        if (reason instanceof ApiError && reason.status === 403)
          setDenied(true);
        else
          setError(
            reason instanceof Error
              ? reason.message
              : "운영 상태를 불러오지 못했습니다.",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [request, revision]);
  const repository = safeRepositoryUrl(data?.source_repository_url);
  return (
    <div className="admin-console">
      <div className="admin-intro">
        <div>
          <span className="eyebrow">CARE FOR YOUR WORKSPACE</span>
          <h2>작업실 운영 현황</h2>
          <p>내 계정의 실행과 연결 상태를 한눈에 확인하세요.</p>
        </div>
        <button
          className="secondary"
          disabled={loading}
          onClick={() => setRevision((value) => value + 1)}
        >
          {loading ? "확인 중…" : "새로고침"}
        </button>
      </div>
      {loading && (
        <p role="status" className="admin-loading">
          서버에서 관리자 권한과 운영 상태를 확인하고 있어요.
        </p>
      )}
      {denied && (
        <section className="admin-denied" role="alert">
          <span aria-hidden="true">◇</span>
          <h3>이 계정에는 관리자 권한이 없습니다.</h3>
          <p>
            관리자 화면은 서버에서 허용한 계정으로만 열 수 있습니다. 현재 계정을
            확인해 주세요.
          </p>
          <button className="secondary" onClick={onSettings}>
            계정 설정으로 돌아가기
          </button>
        </section>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {data && (
        <>
          <p className="admin-scope">{data.notice} · 현재 로그인한 계정 기준</p>
          <div className="admin-counts">
            {Object.entries(data.counts).map(([key, count]) => (
              <div key={key}>
                <span>{countLabels[key as keyof AdminStatus["counts"]]}</span>
                <strong>{Number(count).toLocaleString()}</strong>
              </div>
            ))}
          </div>
          <div className="admin-grid">
            <section className="admin-card">
              <h3>서비스 연결</h3>
              <dl className="admin-connections">
                <div>
                  <dt>실행 환경</dt>
                  <dd>{data.environment}</dd>
                </div>
                <div>
                  <dt>로그인</dt>
                  <dd>
                    {data.authentication_mode === "local"
                      ? "로컬 개인 토큰"
                      : "계정 로그인"}
                  </dd>
                </div>
                <div>
                  <dt>자료 저장</dt>
                  <dd>
                    {data.database.status === "ok" ? "응답 정상" : "확인 필요"}{" "}
                    · {data.database.dialect}
                  </dd>
                </div>
                {data.connections.map((connection) => (
                  <div key={connection.key}>
                    <dt>{connection.label}</dt>
                    <dd>
                      <strong>
                        {stateLabels[connection.status.toUpperCase()] ||
                          "확인 필요"}
                      </strong>
                      <small>{connection.detail}</small>
                    </dd>
                  </div>
                ))}
              </dl>
              <button className="text-button" onClick={onSettings}>
                연결 설정 열기 →
              </button>
            </section>
            <section className="admin-card">
              <h3>사용량과 예약</h3>
              {(
                [
                  ["오늘", data.usage.daily],
                  ["이번 달", data.usage.monthly],
                ] as const
              ).map(([label, total]) => (
                <div className="admin-usage-period" key={label}>
                  <strong>
                    {label} · {data.usage.timezone}
                  </strong>
                  <p>
                    사용·예약 합계 {total.calls.toLocaleString()}회 ·{" "}
                    {total.tokens.toLocaleString()} 토큰
                  </p>
                  <small>
                    예약 {total.reserved_calls.toLocaleString()}회 ·{" "}
                    {total.reserved_tokens.toLocaleString()} 토큰
                  </small>
                  <small>
                    남은 호출 상한 {total.remaining_calls.toLocaleString()}회
                  </small>
                  <small>
                    추정 비용{" "}
                    {typeof total.estimated_cost_usd === "number"
                      ? `$${total.estimated_cost_usd.toFixed(4)}`
                      : "미확인"}
                  </small>
                </div>
              ))}
              <p className="muted">{data.usage.notice}</p>
            </section>
            <section className="admin-card admin-source-card">
              <div className="admin-code-icon" aria-hidden="true">
                &lt;/&gt;
              </div>
              <div>
                <h3>현재 코드, GitHub에서</h3>
                <p>
                  {repository
                    ? "설정한 소스 저장소를 엽니다. 원격 코드의 최신 반영 여부는 저장소에서 확인하세요."
                    : "소스 저장소 연결 전입니다. 저장소가 연결되면 여기에서 현재 코드를 볼 수 있어요."}
                </p>
                {repository ? (
                  <a
                    className="admin-repository-link"
                    href={repository}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    GitHub 코드 열기 ↗
                  </a>
                ) : (
                  <span className="admin-unconnected">GitHub 연결 전</span>
                )}
              </div>
            </section>
          </div>
          <section className="admin-card">
            <div className="admin-runs-heading">
              <h3>최근 실행과 실패</h3>
              <small>오류 유형과 처리 시간</small>
            </div>
            {data.recent_executions.length ? (
              <ol className="admin-runs">
                {data.recent_executions.map((run) => (
                  <li key={run.id}>
                    <div>
                      <strong>{run.label}</strong>
                      <time dateTime={run.started_at}>
                        {new Date(run.started_at).toLocaleString("ko-KR", {
                          timeZone: "Asia/Seoul",
                        })}
                      </time>
                    </div>
                    <div>
                      <span
                        className={
                          run.status === "FAILED" ? "admin-run-failed" : ""
                        }
                      >
                        {stateLabels[run.status] || "상태 확인 필요"}
                      </span>
                      {run.elapsed_ms !== null && (
                        <small>{(run.elapsed_ms / 1000).toFixed(1)}초</small>
                      )}
                      {run.error_code && <small>오류 {run.error_code}</small>}
                    </div>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="muted">실행 기록이 아직 없습니다.</p>
            )}
          </section>
        </>
      )}
    </div>
  );
}
