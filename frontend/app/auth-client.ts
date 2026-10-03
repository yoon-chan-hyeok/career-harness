export type AuthConfiguration = {
  provider: "local" | "supabase";
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
const storageKey = "career-supabase-session";

export function configureAuth(value: AuthConfiguration) {
  if (value.provider !== "local" && value.provider !== "supabase")
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
  if (value.provider === "supabase" && typeof window !== "undefined") {
    try {
      const saved: AuthSession = JSON.parse(
        sessionStorage.getItem(storageKey) || "null",
      );
      if (
        saved?.project === value.supabase_url &&
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

export function clearSession() {
  sessionGeneration++;
  session = null;
  refreshPromise = null;
  if (typeof window !== "undefined") sessionStorage.removeItem(storageKey);
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
