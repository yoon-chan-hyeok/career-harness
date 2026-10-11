"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

type Request = (path: string, body?: unknown) => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Provider = "none" | "huggingface" | "groq" | "openai";
type EditableProvider = Exclude<Provider, "openai">;
type ProviderSummary = {
  provider: Provider;
  model: string;
  configured: boolean;
  live_verified: boolean;
  verified_at: string | null;
  editable: boolean;
  credential_source: "server_environment" | "local_private_file" | "missing";
  free_only_confirmed: boolean;
  token_configured: boolean;
  error?: string;
};
type ProviderActivity = {
  last_success: null | {
    provider: string;
    model: string;
    at: string;
    stage: string;
    latency_ms: number | null;
    current_configuration_matches: boolean;
  };
  notice: string;
};

const defaults: Record<EditableProvider, string> = {
  none: "",
  huggingface: "openai/gpt-oss-120b:fireworks-ai",
  groq: "openai/gpt-oss-120b",
};
const names: Record<Provider, string> = {
  none: "직접 작성",
  huggingface: "Hugging Face",
  groq: "Groq",
  openai: "OpenAI",
};

export function ProviderSettings({
  request,
  onChanged,
}: {
  request: Request;
  onChanged: () => Promise<void> | void;
}) {
  const [summary, setSummary] = useState<ProviderSummary | null>(null);
  const [provider, setProvider] = useState<EditableProvider>("none");
  const [model, setModel] = useState("");
  const [token, setToken] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState<"loading" | "saving" | "checking" | null>(
    "loading",
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [activity, setActivity] = useState<ProviderActivity | null>(null);
  const [activityError, setActivityError] = useState("");
  const generation = useRef(0);
  const refreshActivity = useCallback(async () => {
    const current = generation.current;
    try {
      const next: ProviderActivity = await request("/providers/activity");
      if (generation.current === current) {
        setActivity(next);
        setActivityError("");
      }
    } catch {
      if (generation.current === current)
        setActivityError(
          "지원 작업의 실제 AI 호출 기록을 불러오지 못했습니다.",
        );
    }
  }, [request]);
  const apply = useCallback((next: ProviderSummary) => {
    setSummary(next);
    const selected =
      next.provider === "none"
        ? "groq"
        : next.provider === "openai"
          ? "none"
          : next.provider;
    setProvider(selected);
    setModel(
      next.provider === selected
        ? next.model || defaults[selected]
        : defaults[selected],
    );
    setConfirmed(next.free_only_confirmed);
  }, []);

  useEffect(() => {
    const current = ++generation.current;
    setToken("");
    setSummary(null);
    setActivity(null);
    setActivityError("");
    setError("");
    setNotice("");
    setBusy("loading");
    void refreshActivity();
    request("/providers")
      .then((next: ProviderSummary) => {
        if (generation.current === current) apply(next);
      })
      .catch(() => {
        if (generation.current === current)
          setError(
            "AI 연결 설정을 불러오지 못했습니다. 연결 상태를 확인해 주세요.",
          );
      })
      .finally(() => {
        if (generation.current === current) setBusy(null);
      });
    return () => {
      generation.current = current + 1;
    };
  }, [request, apply, refreshActivity]);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    if (!summary?.editable || busy || (provider !== "none" && !confirmed))
      return;
    const current = generation.current;
    const body = {
      provider,
      model: provider === "none" ? "" : model.trim(),
      ...(token.trim() ? { token: token.trim() } : {}),
      free_only_confirmed: provider !== "none" && confirmed,
    };
    setBusy("saving");
    setError("");
    setNotice("");
    try {
      const next: ProviderSummary = await request("/providers/configure", body);
      if (generation.current !== current) return;
      apply(next);
      setToken("");
      await onChanged();
      await refreshActivity();
      if (generation.current === current)
        setNotice(
          provider === "none"
            ? "직접 작성 모드로 저장했습니다."
            : "저장했습니다. 연결 검사로 실제 응답을 확인하세요.",
        );
    } catch (error) {
      if (generation.current === current)
        setError(
          error instanceof Error
            ? error.message
            : "저장하지 못했습니다. 토큰·모델과 무료 사용 확인을 다시 확인해 주세요.",
        );
    } finally {
      if (generation.current === current) {
        setToken("");
        setBusy(null);
      }
    }
  };

  const check = async () => {
    if (
      !summary?.editable ||
      !summary.configured ||
      !["huggingface", "groq"].includes(summary.provider) ||
      busy
    )
      return;
    const current = generation.current;
    setBusy("checking");
    setError("");
    setNotice("");
    try {
      const next: ProviderSummary = await request("/providers/check", {});
      if (generation.current !== current) return;
      setSummary(next);
      await onChanged();
      await refreshActivity();
      if (generation.current === current)
        setNotice(
          next.live_verified
            ? "짧은 한국어 요청의 실제 응답을 확인했습니다."
            : "응답을 확인하지 못했습니다. 저장한 설정과 제공자 사용 한도를 확인하세요.",
        );
    } catch (error) {
      if (generation.current === current)
        setError(
          error instanceof Error
            ? error.message
            : "연결 검사에 실패했습니다. 토큰 권한·모델·무료 사용 한도를 확인해 주세요.",
        );
    } finally {
      if (generation.current === current) setBusy(null);
    }
  };

  const existingToken =
    summary?.provider === provider && summary.token_configured;
  const canSave =
    provider === "none" ||
    (confirmed && model.trim() && (token.trim() || existingToken));

  return (
    <section aria-labelledby="provider-settings-title">
      <h3 id="provider-settings-title">AI 연결</h3>
      <p className="muted">
        제공자를 연결하면 직무 분석·작성·검수를 진행할 수 있습니다. 직접 작성
        모드도 계속 사용할 수 있습니다.
      </p>
      {summary && (
        <div className="mapping">
          <strong>{names[summary.provider]}</strong>{" "}
          <span className="badge">
            {summary.provider === "none"
              ? "직접 작성"
              : summary.live_verified
                ? "연결 확인됨"
                : summary.configured
                  ? "설정됨 · 실제 응답 미확인"
                  : "연결되지 않음"}
          </span>
          {summary.model && (
            <p style={{ overflowWrap: "anywhere" }}>모델: {summary.model}</p>
          )}
          {summary.verified_at && (
            <p className="muted">
              마지막 연결 확인:{" "}
              {new Date(summary.verified_at).toLocaleString("ko-KR")}
            </p>
          )}
          <p className="muted">
            {summary.credential_source === "server_environment"
              ? "서버에서 관리하는 연결 설정입니다."
              : summary.credential_source === "local_private_file"
                ? "이 컴퓨터의 비공개 설정에 저장돼 있습니다."
                : "등록된 연결 키가 없습니다."}
          </p>
          {summary.error && (
            <p className="error" role="alert">
              {summary.error}
            </p>
          )}
        </div>
      )}
      <div className="provider-activity">
        <strong>지원 작업의 실제 AI 호출</strong>
        {activity?.last_success ? (
          <>
            <p>
              {activity.last_success.model} ·{" "}
              {new Date(activity.last_success.at).toLocaleString("ko-KR")}
            </p>
            {typeof activity.last_success.latency_ms === "number" && (
              <small className="muted">
                응답 시간 {(activity.last_success.latency_ms / 1000).toFixed(1)}
                초
              </small>
            )}
            {!activity.last_success.current_configuration_matches && (
              <p className="note">
                이 기록의 제공자·모델은 현재 선택한 제공자·모델과 다릅니다.
              </p>
            )}
          </>
        ) : activity ? (
          <p className="muted">지원 작업의 실제 AI 호출 기록 없음</p>
        ) : !activityError ? (
          <p className="muted">호출 기록을 확인하고 있어요…</p>
        ) : null}
        {activity?.notice && <p className="muted">{activity.notice}</p>}
        {activityError && (
          <p className="error" role="alert">
            {activityError}
          </p>
        )}
        <button
          className="text-button"
          disabled={Boolean(busy)}
          onClick={() => void refreshActivity()}
        >
          실제 호출 기록 새로고침
        </button>
      </div>
      {summary?.editable && (
        <form onSubmit={(event) => void save(event)}>
          <label>
            사용할 제공자
            <select
              value={provider}
              disabled={Boolean(busy)}
              onChange={(event) => {
                const selected = event.target.value as EditableProvider;
                setProvider(selected);
                setModel(
                  summary.provider === selected
                    ? summary.model || defaults[selected]
                    : defaults[selected],
                );
                setToken("");
                setConfirmed(false);
                setError("");
                setNotice("");
              }}
            >
              <option value="none">직접 작성</option>
              <option value="huggingface">Hugging Face</option>
              <option value="groq">Groq · 무료 한도 확인 후 연결</option>
            </select>
          </label>
          {summary.provider === "none" && (
            <p className="muted">
              현재는 직접 작성 모드입니다. 제공자의 무료 사용 조건을 확인한 뒤
              키를 입력하고 저장하세요. 선택만으로 연결되지는 않습니다.
            </p>
          )}
          {summary.provider === "openai" && (
            <p className="muted">
              현재 OpenAI 설정을 사용합니다. 아래 선택은 저장할 때 적용됩니다.
            </p>
          )}
          {provider !== "none" && (
            <>
              <p className="muted">
                {provider === "huggingface" ? (
                  <>
                    현재 공식 안내상 무료 계정에는 기본 추론 크레딧이 없습니다.
                    토큰 발급만으로 무료 호출이 가능해지지 않습니다.{" "}
                    <a
                      href="https://huggingface.co/docs/inference-providers/pricing"
                      target="_blank"
                      rel="noreferrer"
                    >
                      공식 요금 안내
                    </a>
                  </>
                ) : (
                  <>
                    Groq Free 플랜에는 모델별 요청·토큰 한도가 있습니다.{" "}
                    <a
                      href="https://console.groq.com/docs/rate-limits"
                      target="_blank"
                      rel="noreferrer"
                    >
                      공식 사용 한도
                    </a>
                  </>
                )}
              </p>
              <label>
                {provider === "huggingface"
                  ? "Hugging Face 토큰"
                  : "Groq API 키"}
                <input
                  type="password"
                  autoComplete="off"
                  spellCheck={false}
                  value={token}
                  disabled={Boolean(busy)}
                  placeholder={
                    existingToken
                      ? "비워두면 이 제공자의 기존 키 유지"
                      : "발급한 키를 입력하세요"
                  }
                  onChange={(event) => setToken(event.target.value)}
                />
              </label>
              <p className="muted">
                <a
                  href={
                    provider === "huggingface"
                      ? "https://huggingface.co/settings/tokens"
                      : "https://console.groq.com/keys"
                  }
                  target="_blank"
                  rel="noreferrer"
                >
                  {provider === "huggingface"
                    ? "Hugging Face에서 토큰 발급"
                    : "Groq에서 키 발급"}
                </a>
                {provider === "huggingface" &&
                  " · Make calls to Inference Providers 권한이 필요합니다."}{" "}
                입력한 키는 저장 후 화면에서 지우며, 브라우저 저장소에 보관하지
                않습니다.
              </p>
              <details>
                <summary>모델 설정 · 고급</summary>
                <label>
                  모델 이름
                  <input
                    value={model}
                    autoComplete="off"
                    spellCheck={false}
                    disabled={Boolean(busy)}
                    onChange={(event) => setModel(event.target.value)}
                  />
                </label>
                <p className="muted">
                  기본 모델: {defaults[provider]}. 변경할 경우 제공자의 지원
                  여부와 무료 사용 한도를 확인하세요.
                </p>
              </details>
              <label className="check">
                <input
                  type="checkbox"
                  checked={confirmed}
                  required
                  disabled={Boolean(busy)}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                <span>
                  이 계정의 무료 플랜 또는 무료 크레딧 범위와 과금 설정을
                  제공자에서 직접 확인했습니다.
                </span>
              </label>
              <p className="muted">
                한도 오류가 나면 다른 유료 제공자로 자동 전환하지 않습니다. 실제
                과금은 제공자 계정 설정에 따르며, 이 확인만으로 무료 사용을
                보장하지는 않습니다.
              </p>
            </>
          )}
          <button type="submit" disabled={Boolean(busy) || !canSave}>
            {busy === "saving"
              ? "저장 중…"
              : provider === "none"
                ? "직접 작성으로 저장"
                : "연결 설정 저장"}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={
              Boolean(busy) ||
              !summary.configured ||
              !["huggingface", "groq"].includes(summary.provider)
            }
            onClick={() => void check()}
          >
            {busy === "checking" ? "응답 확인 중…" : "연결 검사"}
          </button>
          <p className="muted">
            연결 검사는 저장한 설정으로 짧은 합성 한국어 문장을 실제 전송합니다.
            경험·이력서·지원 문서는 보내지 않습니다.
          </p>
        </form>
      )}
      {summary && !summary.editable && (
        <p className="muted">
          현재 계정에서는 연결 상태만 확인할 수 있습니다. 설정 변경은 서버를
          관리하는 계정에서 진행하세요.
        </p>
      )}
      {busy === "loading" && (
        <p role="status">연결 설정을 불러오는 중입니다…</p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
    </section>
  );
}
