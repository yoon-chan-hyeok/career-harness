export type WorkroomRole = {
  key: string;
  label: string;
  status: string;
  message: string;
  basis: string;
  artifact_id: string | null;
  artifact_version: number | null;
  execution_run_id: string | null;
  trace_id: string | null;
  provider: string | null;
  model: string | null;
  updated_at: string | null;
};

export const workroomRoles = [
  { key: "research", name: "리서처", color: "#b37951", hair: "#5b4233" },
  {
    key: "opportunity",
    name: "직무 분석가",
    color: "#748666",
    hair: "#403c37",
  },
  {
    key: "evidence",
    name: "근거 연결 담당",
    color: "#718899",
    hair: "#72523d",
  },
  { key: "strategy", name: "지원 전략가", color: "#a78083", hair: "#4f3743" },
  { key: "writing", name: "문서 작성자", color: "#aa925c", hair: "#4d4338" },
  { key: "review", name: "검수 담당", color: "#9280a2", hair: "#504057" },
] as const;

// A configured repository link must never carry credentials, queries or a file path.
export function safeRepositoryUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    if (
      url.protocol !== "https:" ||
      url.hostname !== "github.com" ||
      url.port ||
      url.username ||
      url.password ||
      url.search ||
      url.hash ||
      !/^\/[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9_.-]+\/?$/.test(
        url.pathname,
      )
    )
      return null;
    return url.href.replace(/\/$/, "");
  } catch {
    return null;
  }
}

// Missing server records remain empty; the browser never invents agent dialogue.
export function recordedMessages(roles: WorkroomRole[]): WorkroomRole[] {
  return roles
    .filter(
      (role) =>
        role.message.trim() &&
        (role.artifact_id || role.execution_run_id || role.trace_id),
    )
    .sort((a, b) => (b.updated_at || "").localeCompare(a.updated_at || ""));
}
