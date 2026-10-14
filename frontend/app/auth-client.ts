export type AuthConfiguration = {
  provider: "local" | "supabase" | "guest";
  supabase_url?: string;
  publishable_key?: string;
};

type AuthSession = {
  access_token: string;
  refresh_token: string;
  expires_at: number;
  project: string;
};

let configuration: AuthConfiguration | null = null;
let session: AuthSession | null = null;
let refreshPromise: Promise<string> | null = null;
let sessionGeneration = 0;
let emailGeneration = 0;
const storageKey = "career-supabase-session";

export function configureAuth(value: AuthConfiguration) {
  if (!["local", "supabase", "guest"].includes(value.provider))
    throw new Error("로그인 설정을 확인해 주세요.");
  if (value.provider === "supabase") {
    const url = new URL(value.supabase_url || "");
    if (
      url.protocol !== "https:" ||
      url.username ||
      url.password ||
      url.pathname !== "/" ||
      url.search ||
      url.hash ||
      !value.publishable_key
    )
      throw new Error("로그인 설정을 확인해 주세요.");
  }
  if (
    (configuration && configuration.supabase_url !== value.supabase_url) ||
    value.provider === "local"
  )
    clearSession();
  configuration = value;
  if (value.provider !== "local" && typeof window !== "undefined") {
    try {
      const saved: AuthSession = JSON.parse(
        sessionStorage.getItem(storageKey) || "null",
      );
      if (
        saved?.project ===
          (value.provider === "guest" ? "guest" : value.supabase_url) &&
        typeof saved.access_token === "string" &&
        typeof saved.refresh_token === "string" &&
        Number.isFinite(saved.expires_at)
      )
        session = saved;
      else {
        session = null;
        sessionStorage.removeItem(storageKey);
      }
    } catch {
      session = null;
      sessionStorage.removeItem(storageKey);
    }
  }
}

function authEndpoint(path: string) {
  if (configuration?.provider !== "supabase")
    throw new Error("로그인 설정을 확인해 주세요.");
  return configuration.supabase_url!.replace(/\/$/, "") + "/auth/v1" + path;
}

async function exchange(
  grant: "password" | "refresh_token",
  body: object,
  generation: number,
) {
  const response = await fetch(authEndpoint("/token?grant_type=" + grant), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      apikey: configuration!.publishable_key!,
    },
    body: JSON.stringify(body),
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok)
    throw new Error(
      grant === "password"
        ? "이메일과 비밀번호 또는 계정 설정을 확인해 주세요."
        : "로그인이 만료되었습니다. 다시 로그인해 주세요.",
    );
  const value = await response.json();
  if (generation !== sessionGeneration)
    throw new Error("로그인이 종료되었습니다.");
  if (
    typeof value.access_token !== "string" ||
    typeof value.refresh_token !== "string" ||
    !Number.isFinite(value.expires_in) ||
    value.expires_in <= 0
  )
    throw new Error("로그인 응답을 확인하지 못했습니다.");
  session = {
    access_token: value.access_token,
    refresh_token: value.refresh_token,
    expires_at: Date.now() / 1000 + value.expires_in,
    project: configuration!.supabase_url!,
  };
  sessionStorage.setItem(storageKey, JSON.stringify(session));
  return session.access_token;
}

export async function signIn(email: string, password: string) {
  clearSession();
  const generation = sessionGeneration;
  return exchange("password", { email, password }, generation);
}

export async function accessToken(): Promise<string> {
  if (!session) throw new Error("먼저 로그인해 주세요.");
  if (session.expires_at > Date.now() / 1000 + 30) return session.access_token;
  if (configuration?.provider === "guest") {
    clearSession();
    throw new Error("체험 연결이 만료되었습니다. 새 작업실로 시작해 주세요.");
  }
  if (!refreshPromise) {
    const generation = sessionGeneration;
    const pending = exchange(
      "refresh_token",
      { refresh_token: session.refresh_token },
      generation,
    )
      .catch((error) => {
        if (generation === sessionGeneration) clearSession();
        throw error;
      })
      .finally(() => {
        if (refreshPromise === pending) refreshPromise = null;
      });
    refreshPromise = pending;
  }
  return refreshPromise;
}

export function hasSession() {
  return Boolean(session);
}

export async function startGuest() {
  if (configuration?.provider !== "guest")
    throw new Error("현재 게스트 체험을 시작할 수 없습니다.");
  clearSession();
  const generation = sessionGeneration;
  const response = await fetch("/api/auth/guest", {
    method: "POST",
    cache: "no-store",
    credentials: "omit",
    redirect: "error",
    signal: AbortSignal.timeout(30000),
  });
  if (!response.ok)
    throw new Error(
      response.status === 429
        ? "오늘의 체험 시작 한도에 도달했습니다. 저장된 연결을 사용하거나 내일 다시 방문해 주세요."
        : "체험 연결을 만들지 못했습니다. 잠시 후 다시 시도해 주세요.",
    );
  const value = await response.json();
  if (generation !== sessionGeneration)
    throw new Error("연결이 종료되었습니다.");
  if (
    typeof value.access_token !== "string" ||
    value.token_type !== "bearer" ||
    !Number.isFinite(value.expires_in) ||
    value.expires_in <= 0 ||
    value.expires_in > 86400
  )
    throw new Error("체험 응답을 확인하지 못했습니다.");
  session = {
    access_token: value.access_token,
    refresh_token: "",
    expires_at: Date.now() / 1000 + value.expires_in,
    project: "guest",
  };
  sessionStorage.setItem(storageKey, JSON.stringify(session));
}

export function clearSession() {
  sessionGeneration++;
  emailGeneration++;
  session = null;
  refreshPromise = null;
  if (typeof window !== "undefined") sessionStorage.removeItem(storageKey);
}

export function cancelEmailAuthentication() {
  emailGeneration++;
}

const emailError =
  "이메일 인증을 완료하지 못했습니다. 주소와 코드를 확인하거나 잠시 후 다시 시도해 주세요.";

async function emailRequest(path: string, body: object) {
  try {
    const response = await fetch(authEndpoint(path), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        apikey: configuration!.publishable_key!,
      },
      body: JSON.stringify(body),
      cache: "no-store",
      credentials: "omit",
      redirect: "error",
      signal: AbortSignal.timeout(15000),
    });
    if (!response.ok) throw new Error(emailError);
    return response;
  } catch {
    throw new Error(emailError);
  }
}

export async function requestEmailCode(
  email: string,
  captchaToken: string,
  options: { createUser?: boolean; reauthentication?: boolean } = {},
) {
  if (!captchaToken.trim()) throw new Error("보안 확인을 먼저 완료해 주세요.");
  if (!options.reauthentication) clearSession();
  const challenge = ++emailGeneration;
  await emailRequest("/otp", {
    email: email.trim(),
    create_user: options.createUser ?? true,
    gotrue_meta_security: { captcha_token: captchaToken },
  });
  if (challenge !== emailGeneration)
    throw new Error("이메일 인증이 취소되었습니다.");
  return challenge;
}

export async function verifyEmailCode(
  email: string,
  token: string,
  challenge: number,
  persist = true,
) {
  if (challenge !== emailGeneration)
    throw new Error("이메일 인증을 다시 시작해 주세요.");
  const generation = sessionGeneration;
  const response = await emailRequest("/verify", {
    email: email.trim(),
    token: token.trim(),
    type: "email",
  });
  const value = await response.json();
  if (challenge !== emailGeneration || generation !== sessionGeneration)
    throw new Error("이메일 인증이 취소되었습니다.");
  if (
    typeof value.access_token !== "string" ||
    !value.access_token ||
    typeof value.refresh_token !== "string" ||
    !value.refresh_token ||
    !Number.isFinite(value.expires_in) ||
    value.expires_in <= 0 ||
    !(value.user?.email_confirmed_at || value.user?.confirmed_at) ||
    typeof value.user?.email !== "string" ||
    value.user.email.toLowerCase() !== email.trim().toLowerCase()
  )
    throw new Error(emailError);
  if (persist) {
    session = {
      access_token: value.access_token,
      refresh_token: value.refresh_token,
      expires_at: Date.now() / 1000 + value.expires_in,
      project: configuration!.supabase_url!,
    };
    sessionStorage.setItem(storageKey, JSON.stringify(session));
  }
  emailGeneration++;
  return value.access_token as string;
}

export async function signOut() {
  const token = session?.access_token;
  clearSession();
  if (!token || configuration?.provider !== "supabase") return;
  const response = await fetch(authEndpoint("/logout?scope=local"), {
    method: "POST",
    headers: {
      apikey: configuration.publishable_key!,
      Authorization: "Bearer " + token,
    },
    credentials: "omit",
    redirect: "error",
    cache: "no-store",
    signal: AbortSignal.timeout(10000),
  });
  if (!response.ok && response.status !== 401)
    throw new Error(
      "이 기기에서는 로그아웃했습니다. 서버 세션 종료는 연결 후 다시 확인해 주세요.",
    );
}
