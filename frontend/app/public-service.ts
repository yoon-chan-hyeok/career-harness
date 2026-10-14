export type PublicService = {
  access_mode: "invite" | "public";
  guest_enabled?: boolean;
  guest_session_seconds?: number | null;
  support_url?: string;
  registration_open: boolean;
  policy_version: string;
  operator_name: string;
  support_email: string;
  privacy_url: string;
  terms_url: string;
  captcha_site_key: string;
  public_limits: {
    daily_calls: number;
    monthly_calls: number;
    daily_tokens: number;
    monthly_tokens: number;
  };
  retention_days: number | null;
  backup_retention_days: number | null;
  ai_provider: string;
  service_name: string;
};

export async function loadPublicService(): Promise<PublicService> {
  const response = await fetch("/api/service/public", {
    cache: "no-store",
    signal: AbortSignal.timeout(15000),
  });
  if (!response.ok)
    throw new Error(
      "서비스 안내를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    );
  return response.json();
}

export const providerNames: Record<string, string> = {
  none: "미연결",
  huggingface: "Hugging Face",
  hugging_face: "Hugging Face",
  hf: "Hugging Face",
  groq: "Groq",
  openai: "OpenAI",
};
