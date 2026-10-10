"use client";
import Script from "next/script";
import { FormEvent, useEffect, useRef, useState } from "react";
import {
  cancelEmailAuthentication,
  requestEmailCode,
  verifyEmailCode,
} from "./auth-client";

type TurnstileApi = {
  render: (container: HTMLElement, options: Record<string, unknown>) => string;
  remove: (id: string) => void;
};
declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

function SecurityCheck({
  siteKey,
  onToken,
}: {
  siteKey: string;
  onToken: (token: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!loaded || !container.current || !window.turnstile) return;
    let active = true;
    const widget = window.turnstile.render(container.current, {
      sitekey: siteKey,
      theme: "light",
      size: "compact",
      callback: (value: string) => {
        if (active) onToken(value);
      },
      "expired-callback": () => {
        if (active) onToken("");
      },
      "error-callback": () => {
        if (active) {
          onToken("");
          setFailed(true);
        }
      },
    });
    return () => {
      active = false;
      window.turnstile?.remove(widget);
    };
  }, [loaded, siteKey, onToken]);
  return (
    <div className="security-check">
      <Script
        id="career-turnstile"
        src="https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit"
        strategy="afterInteractive"
        onReady={() => setLoaded(true)}
        onError={() => setFailed(true)}
      />
      <div ref={container} />
      {failed && (
        <p role="alert">
          보안 확인을 불러오지 못했습니다. 연결 상태를 확인하고 새로고침해
          주세요.
        </p>
      )}
    </div>
  );
}

export function EmailCodeForm({
  siteKey,
  createUser,
  reauthenticate = false,
  onVerified,
}: {
  siteKey: string;
  createUser: boolean;
  reauthenticate?: boolean;
  onVerified: (token: string) => Promise<void>;
}) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [captchaToken, setCaptchaToken] = useState("");
  const [challenge, setChallenge] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [remaining, setRemaining] = useState(0);
  const [widgetKey, setWidgetKey] = useState(0);
  const mounted = useRef(true);
  const action = useRef(0);
  const retryAfter = useRef(0);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      cancelEmailAuthentication();
    };
  }, []);
  useEffect(() => {
    if (!remaining) return;
    const timer = setInterval(
      () =>
        setRemaining(
          Math.max(0, Math.ceil((retryAfter.current - Date.now()) / 1000)),
        ),
      1000,
    );
    return () => clearInterval(timer);
  }, [remaining]);
  const send = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || Date.now() < retryAfter.current) return;
    const current = ++action.current;
    setBusy(true);
    setError("");
    setMessage("");
    retryAfter.current = Date.now() + 60000;
    setRemaining(60);
    try {
      const value = await requestEmailCode(email, captchaToken, {
        createUser,
        reauthentication: reauthenticate,
      });
      if (!mounted.current || action.current !== current) return;
      setChallenge(value);
      setMessage(
        "인증 요청을 처리했습니다. 이메일에 도착한 코드를 입력해 주세요. 메일이 없다면 스팸함도 확인하세요.",
      );
    } catch (error) {
      if (mounted.current && action.current === current)
        setError(
          error instanceof Error
            ? error.message
            : "이메일 인증 요청을 완료하지 못했습니다.",
        );
    } finally {
      if (mounted.current && action.current === current) {
        setBusy(false);
        setCaptchaToken("");
        setWidgetKey((value) => value + 1);
      }
    }
  };
  const verify = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || challenge === null) return;
    const current = ++action.current;
    setBusy(true);
    setError("");
    try {
      const token = await verifyEmailCode(
        email,
        code,
        challenge,
        !reauthenticate,
      );
      if (!mounted.current || action.current !== current) return;
      await onVerified(token);
    } catch (error) {
      if (mounted.current && action.current === current)
        setError(
          error instanceof Error
            ? error.message
            : "인증 코드를 확인하지 못했습니다.",
        );
    } finally {
      if (mounted.current && action.current === current) setBusy(false);
    }
  };
  const reset = () => {
    action.current++;
    cancelEmailAuthentication();
    setChallenge(null);
    setCode("");
    setError("");
    setMessage("");
    setBusy(false);
    setCaptchaToken("");
    setWidgetKey((value) => value + 1);
  };
  return (
    <div className="email-code-form">
      <form onSubmit={send}>
        <label>
          이메일
          <input
            required
            type="email"
            autoComplete="email"
            maxLength={254}
            value={email}
            disabled={challenge !== null || busy}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        {siteKey ? (
          <SecurityCheck
            key={widgetKey}
            siteKey={siteKey}
            onToken={setCaptchaToken}
          />
        ) : (
          <p role="status">
            이메일 로그인 준비 중입니다. 잠시 후 다시 방문해 주세요.
          </p>
        )}
        <button
          className="primary"
          type="submit"
          disabled={busy || !captchaToken || remaining > 0 || !email}
        >
          {remaining > 0
            ? remaining + "초 후 다시 보내기"
            : challenge !== null
              ? "인증 코드 다시 보내기"
              : "이메일로 인증 코드 받기"}
        </button>
      </form>
      {challenge !== null && (
        <form onSubmit={verify}>
          <label>
            이메일 인증 코드
            <input
              required
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6,8}"
              minLength={6}
              maxLength={8}
              value={code}
              onChange={(event) =>
                setCode(event.target.value.replace(/[^0-9]/g, ""))
              }
            />
          </label>
          <button type="submit" disabled={busy || code.length < 6}>
            {busy
              ? "확인 중…"
              : reauthenticate
                ? "본인 확인 완료"
                : "인증하고 시작하기"}
          </button>
          <button type="button" className="secondary" onClick={reset}>
            이메일 변경·취소
          </button>
        </form>
      )}
      {message && (
        <p className="note" role="status">
          {message}
        </p>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
