"use client";

import { FormEvent, useEffect, useState } from "react";
import type { Request } from "./api-client";

type Limits = Record<string, number | null>;
type Member = {
  user_id: string;
  status: "ACTIVE" | "SUSPENDED";
  limits: Limits;
};
type Service = {
  access_mode: "public" | "invite";
  next_cursor: string | null;
  total_members: number;
  enabled: boolean;
  notice: string;
  members: Member[];
  shared_usage: {
    limits: Limits;
    daily: { calls: number; tokens: number };
    monthly: { calls: number; tokens: number };
  };
};
const labels: Record<string, string> = {
  daily_calls: "하루 호출",
  monthly_calls: "월 호출",
  daily_tokens: "하루 토큰",
  monthly_tokens: "월 토큰",
  daily_cost_usd: "하루 비용 상한($)",
  monthly_cost_usd: "월 비용 상한($)",
};

export function ServiceConsole({ request }: { request: Request }) {
  const [data, setData] = useState<Service | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [member, setMember] = useState<Member | null>(null);
  const [revision, setRevision] = useState(0);
  const [cursor, setCursor] = useState("");
  const [prefix, setPrefix] = useState("");
  useEffect(() => {
    let active = true;
    request("/admin/service?" + new URLSearchParams({ after: cursor, prefix }))
      .then((value: Service) => {
        if (active) setData(value);
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : "운영 설정을 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, [request, revision, cursor, prefix]);
  const save = async (event: FormEvent<HTMLFormElement>, shared: boolean) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const limits = Object.fromEntries(
      Object.keys(labels).map((key) => [
        key,
        form.get(key) === "" ? null : Number(form.get(key)),
      ]),
    );
    setBusy(true);
    setError("");
    try {
      await request(
        shared ? "/admin/service/limits" : "/admin/service/members",
        shared
          ? limits
          : {
              user_id: String(form.get("user_id") || "").trim(),
              status: form.get("status"),
              limits,
            },
        "PUT",
      );
      setMember(null);
      setRevision((value) => value + 1);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "설정을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  const fields = (limits: Limits) =>
    Object.entries(labels).map(([key, label]) => (
      <label key={key}>
        {label}
        <input
          name={key}
          type="number"
          min="0"
          max={key.endsWith("usd") ? 1000 : 100000000}
          step={key.endsWith("usd") ? "0.0001" : "1"}
          required={!key.endsWith("usd")}
          defaultValue={limits[key] ?? ""}
        />
      </label>
    ));
  return (
    <section className="admin-card service-console">
      <h3>
        {data?.access_mode === "public"
          ? "공개 가입 계정과 공용 AI 한도"
          : "초대 계정과 공용 AI 한도"}
      </h3>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {data ? (
        <>
          <p>{data.notice}</p>
          {!data.enabled && (
            <p className="muted">
              현재는 개인 로컬 모드입니다. 공용 운영 모드에서 아래 접근 제한과
              공용 한도가 적용됩니다.
            </p>
          )}
          <p>
            공용 사용·예약: 오늘{" "}
            {data.shared_usage.daily.calls.toLocaleString()}회 /{" "}
            {data.shared_usage.daily.tokens.toLocaleString()}토큰 · 이번 달{" "}
            {data.shared_usage.monthly.calls.toLocaleString()}회
          </p>
          <details>
            <summary>서비스 전체 상한 변경</summary>
            <form
              key={`shared:${revision}`}
              onSubmit={(event) => void save(event, true)}
            >
              <div className="service-limit-fields">
                {fields(data.shared_usage.limits)}
              </div>
              <p className="muted">
                호출 상한 0은 새 AI 실행을 중지합니다. 이미 시작한 호출은
                취소되지 않습니다. 비용이 미확인이면 설정한 비용 상한으로 실행할
                수 없습니다.
              </p>
              <button disabled={busy}>공용 상한 저장</button>
            </form>
          </details>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              setCursor("");
              setPrefix(
                String(
                  new FormData(event.currentTarget).get("prefix") || "",
                ).trim(),
              );
            }}
          >
            <label>
              사용자 ID로 찾기
              <input
                name="prefix"
                maxLength={64}
                placeholder="ID 전체 또는 앞부분"
              />
            </label>
            <button className="secondary">계정 찾기</button>
          </form>
          <p className="muted">
            조회된 계정 {data.total_members}개 · 한 번에 50개씩 표시
          </p>
          <ul className="service-members">
            {data.members.map((item) => (
              <li key={item.user_id}>
                <span>
                  <strong>{item.user_id}</strong>
                  <small>
                    {item.status === "ACTIVE" ? "접근 허용" : "접근 중지"} ·
                    하루 {item.limits.daily_calls}회
                  </small>
                </span>
                <button
                  className="secondary"
                  disabled={busy}
                  onClick={() => setMember(item)}
                >
                  관리
                </button>
              </li>
            ))}
          </ul>
          <div className="public-actions">
            {cursor && (
              <button className="secondary" onClick={() => setCursor("")}>
                처음으로
              </button>
            )}
            {data.next_cursor && (
              <button
                className="secondary"
                onClick={() => setCursor(data.next_cursor!)}
              >
                다음 계정
              </button>
            )}
          </div>
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              setMember({
                user_id: "",
                status: "ACTIVE",
                limits: data.shared_usage.limits,
              })
            }
          >
            {data.access_mode === "public"
              ? "계정 정책 등록"
              : "초대 계정 등록"}
          </button>
          {member && (
            <form
              key={member.user_id || "new"}
              onSubmit={(event) => void save(event, false)}
            >
              <label>
                Supabase 계정의 사용자 ID
                <input
                  name="user_id"
                  required
                  maxLength={64}
                  defaultValue={member.user_id}
                  readOnly={Boolean(member.user_id)}
                />
              </label>
              <p className="muted">
                Supabase에서 만든 계정의 UUID를 승인합니다. 이 화면에서 초대
                메일을 보내거나 로그인 계정을 만들지는 않습니다.
              </p>
              <label>
                접근 상태
                <select name="status" defaultValue={member.status}>
                  <option value="ACTIVE">접근 허용</option>
                  <option value="SUSPENDED">접근 중지</option>
                </select>
              </label>
              <div className="service-limit-fields">
                {fields(member.limits)}
              </div>
              <button disabled={busy}>계정 정책 저장</button>
              <button
                type="button"
                className="secondary"
                onClick={() => setMember(null)}
              >
                닫기
              </button>
            </form>
          )}
        </>
      ) : (
        <p role="status">운영 설정 확인 중…</p>
      )}
    </section>
  );
}
