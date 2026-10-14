"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { EmailCodeForm } from "./email-code-form";
import { guestSessionInfo, hasSession, startGuest } from "./auth-client";
import { providerNames, type PublicService } from "./public-service";
import type { Request } from "./api-client";
import { GuestSessionNotice } from "./guest-session-notice";

export function PublicFooter({ service }: { service: PublicService }) {
  return (
    <footer className="public-footer">
      <span>
        {service.operator_name ||
          (service.guest_enabled
            ? "Career Harness 공개 체험"
            : "운영 정보 준비 중")}
      </span>
      <nav aria-label="서비스 안내">
        <Link href="/privacy">개인정보 처리방침</Link>
        <Link href="/terms">이용약관</Link>
        {service.support_email && (
          <a href={"mailto:" + service.support_email}>
            {service.support_email}
          </a>
        )}
        {service.guest_enabled && service.support_url && (
          <a href={service.support_url} target="_blank" rel="noreferrer">
            문의·오류 제보
          </a>
        )}
      </nav>
    </footer>
  );
}

export function PublicEntry({
  service,
  onLogin,
  message,
  busy,
}: {
  service: PublicService;
  onLogin: () => Promise<void>;
  message: string;
  busy: boolean;
}) {
  const [starting, setStarting] = useState(false);
  const [guestError, setGuestError] = useState("");
  const [instant, setInstant] = useState(() => Date.now());
  useEffect(() => {
    if (!service.guest_enabled) return;
    const sync = () => setInstant(Date.now());
    const timer = window.setInterval(sync, 30000);
    document.addEventListener("visibilitychange", sync);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", sync);
    };
  }, [service.guest_enabled]);
  const reusableSession = service.guest_enabled
    ? (guestSessionInfo(instant)?.remainingSeconds || 0) > 0
    : hasSession();
  return (
    <main className="public-page">
      <header className="public-header">
        <Link href="/" className="brand">
          <span className="brand-mark">h</span>
          <span>
            {service.service_name || "Career Harness"}
            <small>근거에서 시작하는 지원 준비</small>
          </span>
        </Link>
        <a href="#start" className="public-top-link">
          내 작업실 열기 →
        </a>
      </header>
      <div className="public-hero">
        <div className="public-intro">
          <span className="eyebrow">YOUR CAREER, GROUNDED</span>
          <h1>
            내가 해낸 일에서,
            <br />
            다음 기회까지.
          </h1>
          <p className="public-lead">
            경험을 정리하고, 공고에 맞는 근거를 골라
            <br className="desktop-break" /> 자기소개서와 이력서를 함께
            준비하세요.
          </p>
          <div className="public-benefits">
            <div>
              <span>01</span>
              <strong>경험을 근거로</strong>
              <p>수치와 기여 범위를 확인하며 나만의 자료를 쌓습니다.</p>
            </div>
            <div>
              <span>02</span>
              <strong>대화하며 작성</strong>
              <p>직무 분석부터 문항 작성, 검수까지 한 흐름으로 이어집니다.</p>
            </div>
            <div>
              <span>03</span>
              <strong>문서는 한곳에</strong>
              <p>지원별 초안과 최종본을 보관하고 필요할 때 내려받습니다.</p>
            </div>
          </div>
          <div className="public-preview" aria-label="작업 공간 예시">
            <div className="preview-chat">
              <small>작업 공간 예시</small>
              <p>이 경험에서 제가 맡은 역할을 더 정확하게 표현하고 싶어요.</p>
              <div>확인한 근거에서 역할과 성과를 나누어 정리해 볼게요.</div>
            </div>
            <div className="preview-storage">
              <strong>문서 보관함</strong>
              <span>✓ 경험 정리</span>
              <span>자기소개서 · 작성 중</span>
              <span>이력서 · 검토 대기</span>
            </div>
          </div>
        </div>
        <section
          className="public-auth-card"
          id="start"
          aria-labelledby="start-title"
        >
          <span className="eyebrow">YOUR PRIVATE WORKSPACE</span>
          <h2 id="start-title">나의 커리어 작업실</h2>
          <p>
            {service.guest_enabled
              ? "이메일 가입 없이 별도의 체험 작업실로 시작합니다."
              : "비밀번호 없이 이메일 인증 코드로 로그인합니다."}
            {service.registration_open
              ? service.guest_enabled
                ? " 누구나 무료 한도 안에서 사용할 수 있습니다."
                : " 처음 방문하면 계정을 만들 수 있습니다."
              : "현재 신규 가입은 잠시 중단되어 있습니다. 기존 계정은 로그인할 수 있습니다."}
          </p>
          {service.guest_enabled ? (
            <>
              <p className="note">
                연결은 24시간 동안 이 브라우저 탭에서 유지됩니다. 탭을 닫거나
                로그아웃하면 자료를 다시 찾을 수 없으니 필요한 문서는 내려받아
                보관하세요. 다른 방문자의 자료와는 분리됩니다.
              </p>
              {!reusableSession && (
                <button
                  disabled={busy || starting || !service.registration_open}
                  onClick={async () => {
                    setStarting(true);
                    setGuestError("");
                    try {
                      await startGuest();
                      await onLogin();
                    } catch (error) {
                      setGuestError(
                        error instanceof Error
                          ? error.message
                          : "체험을 시작하지 못했습니다.",
                      );
                    } finally {
                      setStarting(false);
                      setInstant(Date.now());
                    }
                  }}
                >
                  {starting ? "작업실 준비 중…" : "가입 없이 무료로 시작"}
                </button>
              )}
              {guestError && (
                <p role="alert" className="error">
                  {guestError}
                </p>
              )}
            </>
          ) : (
            <EmailCodeForm
              siteKey={service.captcha_site_key}
              createUser={service.registration_open}
              onVerified={onLogin}
            />
          )}
          {reusableSession && (
            <button
              className="secondary"
              disabled={busy}
              onClick={() => void onLogin()}
            >
              {service.guest_enabled
                ? "현재 체험 이어가기"
                : "저장된 로그인으로 연결"}
            </button>
          )}
          {message && (
            <p role="alert" className="error">
              {message}
            </p>
          )}
          <div className="public-limit-note">
            <strong>현재 기본 사용 한도</strong>
            <span>
              AI 하루 {service.public_limits.daily_calls.toLocaleString()}회 ·
              월 {service.public_limits.monthly_calls.toLocaleString()}회
            </span>
            <p>
              서비스 전체 한도와 AI 제공자 사정에 따라 사용이 일시 제한될 수
              있습니다. 자동 유료 전환은 없습니다.
            </p>
          </div>
          <p className="muted">
            연결 후 이용 조건과 자료 처리 안내를 확인합니다. AI 결과는 제출 전
            직접 검토해 주세요.
          </p>
        </section>
      </div>
      <PublicFooter service={service} />
    </main>
  );
}

export function Onboarding({
  service,
  version,
  request,
  onAccepted,
  onCancel,
  onAccount,
}: {
  service: PublicService;
  version: string;
  request: Request;
  onAccepted: () => Promise<void>;
  onCancel: () => void;
  onAccount: () => void;
}) {
  const [terms, setTerms] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  return (
    <main className="public-page">
      <section className="onboarding-card">
        <span className="eyebrow">BEFORE YOU BEGIN</span>
        <h1>작업실을 시작하기 전에</h1>
        <p>
          내 자료가 어떻게 쓰이는지 확인해 주세요. 동의하지 않으면 자료를
          등록하거나 AI 작업을 시작하지 않습니다.
        </p>
        {service.guest_enabled && (
          <GuestSessionNotice request={request} disabled={busy} />
        )}
        <ul>
          <li>
            경험·공고·자기소개서·이력서를 계정별로 저장해 지원 준비에
            사용합니다.
          </li>
          <li>
            AI 기능을 실행하면 필요한 문서와 근거가 설정된 AI 제공자(
            {providerNames[service.ai_provider] ||
              service.ai_provider ||
              "미연결"}
            )에 전송됩니다. 제공자의 처리 조건이 함께 적용됩니다.
          </li>
          <li>
            AI가 만든 사실·수치·기여 범위를 직접 확인해야 합니다. 합격이나
            결과의 정확성을 보장하지 않습니다.
          </li>
          <li>
            주민등록번호, 계좌 정보, 다른 사람의 민감정보는 올리지 마세요.
          </li>
        </ul>
        <label className="consent-check">
          <input
            type="checkbox"
            checked={terms}
            onChange={(event) => setTerms(event.target.checked)}
          />
          <span>
            <Link href="/terms" target="_blank">
              이용약관
            </Link>
            을 읽고 동의합니다. (필수)
          </span>
        </label>
        <label className="consent-check">
          <input
            type="checkbox"
            checked={processing}
            onChange={(event) => setProcessing(event.target.checked)}
          />
          <span>
            <Link href="/privacy" target="_blank">
              개인정보 처리방침
            </Link>
            과 AI 기능 실행 시 외부 제공자에게 자료가 전송되는 내용을 확인하고
            동의합니다. (필수)
          </span>
        </label>
        {error && (
          <p role="alert" className="error">
            {error}
          </p>
        )}
        <div className="public-actions">
          <button
            disabled={!terms || !processing || busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                await request("/account/onboarding", {
                  policy_version: version,
                  accepted: true,
                });
                await onAccepted();
              } catch (error) {
                setError(
                  error instanceof Error
                    ? error.message
                    : "동의를 저장하지 못했습니다.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "저장 중…" : "동의하고 작업실 시작"}
          </button>
          <button className="secondary" disabled={busy} onClick={onCancel}>
            로그아웃
          </button>
        </div>
        <button className="secondary" onClick={onAccount}>
          동의 없이 내 계정 관리
        </button>
        <small>안내 버전 {version}</small>
      </section>
      <PublicFooter service={service} />
    </main>
  );
}
