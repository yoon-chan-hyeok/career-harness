export type Request = (
  path: string,
  body?: unknown,
  method?: string,
) => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const statusMessages: Record<number, string> = {
  401: "로그인이 만료되었습니다. 다시 연결한 뒤 저장된 초안을 불러와 주세요.",
  402: "무료 사용 한도가 소진되었거나 계정의 결제 설정 확인이 필요합니다. 자동으로 유료 호출하지 않습니다.",
  403: "이 작업에 접근할 권한이 없습니다. 현재 로그인한 계정을 확인해 주세요.",
  413: "자료가 너무 큽니다. 파일이나 본문을 나누어 다시 올려 주세요.",
  429: "사용 한도에 도달했습니다. 사용량을 확인하고 잠시 후 같은 작업을 다시 시도해 주세요.",
  502: "AI 제공자와 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.",
  503: "서비스가 잠시 응답하지 않습니다. 잠시 후 같은 작업을 다시 시도해 주세요.",
  504: "작업 응답을 기다리는 시간이 지났습니다. 실행 기록을 확인한 뒤 같은 작업을 다시 시도해 주세요.",
};
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}

export async function responseError(response: Response): Promise<Error> {
  let detail: unknown;
  try {
    detail = (await response.json()).detail;
  } catch {
    /* A proxy may return an HTML error. */
  }
  if (
    response.status === 403 &&
    typeof detail === "object" &&
    detail !== null &&
    "code" in detail &&
    detail.code === "POLICY_ACCEPTANCE_REQUIRED"
  )
    return new ApiError(
      "이용 안내가 변경되었습니다. 로그아웃 후 다시 로그인해 최신 안내를 확인해 주세요. 저장된 자료는 유지됩니다.",
      403,
    );
  const readable =
    typeof detail === "string" && /[가-힣]/.test(detail)
      ? detail.slice(0, 500)
      : "입력 내용과 현재 작업 상태를 확인해 주세요.";
  return new ApiError(
    statusMessages[response.status] ||
      (response.status >= 500
        ? "처리 중 문제가 발생했습니다. 저장된 자료를 확인한 뒤 다시 시도해 주세요."
        : readable),
    response.status,
  );
}

export function createApiClient(
  bearer: () => Promise<string>,
  unauthorized: () => void,
  timeoutMs = 110_000,
) {
  const pending = new Map<string, string>();
  async function send(
    path: string,
    body?: unknown,
    method?: string,
  ): Promise<Response> {
    const verb = method || (body !== undefined ? "POST" : "GET");
    const multipart =
      typeof FormData !== "undefined" && body instanceof FormData;
    const serialized =
      body === undefined
        ? undefined
        : multipart
          ? undefined
          : JSON.stringify(body);
    let signature = "";
    let key = "";
    if (!["GET", "HEAD"].includes(verb) && !multipart) {
      // Retain only a digest, never a token or personal document used in a request.
      const digest = await crypto.subtle.digest(
        "SHA-256",
        new TextEncoder().encode(`${verb}:${path}:${serialized}`),
      );
      signature = Array.from(new Uint8Array(digest), (b) =>
        b.toString(16).padStart(2, "0"),
      ).join("");
      key = pending.get(signature) || crypto.randomUUID();
      if (pending.size >= 128 && !pending.has(signature))
        pending.delete(pending.keys().next().value!);
      pending.set(signature, key);
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch("/api" + path, {
        method: verb,
        cache: "no-store",
        headers: {
          Authorization: "Bearer " + (await bearer()),
          ...(multipart ? {} : { "Content-Type": "application/json" }),
          ...(key ? { "Idempotency-Key": key } : {}),
        },
        body: multipart ? (body as FormData) : serialized,
        signal: controller.signal,
      });
      if (response.status === 401) unauthorized();
      if (
        signature &&
        (response.ok || [400, 403, 404, 422].includes(response.status))
      )
        pending.delete(signature);
      if (!response.ok) throw await responseError(response);
      return response;
    } catch (error) {
      if (controller.signal.aborted) throw new Error(statusMessages[504]);
      if (error instanceof TypeError)
        throw new Error(
          "네트워크 연결이 끊겼습니다. 작업이 저장됐는지 확인한 뒤 같은 내용으로 다시 시도해 주세요.",
        );
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
  const request: Request = async (path, body, method) => {
    const response = await send(path, body, method);
    if (response.status === 204) return null;
    try {
      return await response.json();
    } catch {
      throw new Error(
        "응답 내용을 확인하지 못했습니다. 실행 기록을 확인한 뒤 다시 시도해 주세요.",
      );
    }
  };
  return { request, send, clearPending: () => pending.clear() };
}
