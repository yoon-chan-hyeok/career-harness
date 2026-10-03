"use client";

import type { FeatureExtractionPipeline } from "@huggingface/transformers";

export const LOCAL_EMBEDDING_MODEL = {
  model_id: "Xenova/multilingual-e5-small",
  revision: "761b726dd34fb83930e26aab4e9ac3899aa1fa78",
  dtype: "q8",
  dimensions: 384,
  max_tokens: 512,
  max_text_chars: 6000,
  weight_bytes: 118308185,
} as const;

export type EmbeddingProgress = { message: string; percent?: number };
type ProgressListener = (progress: EmbeddingProgress) => void;
const listeners = new Set<ProgressListener>();
let extractorPromise: Promise<FeatureExtractionPipeline> | null = null;
let pending: Promise<unknown> = Promise.resolve();

function notify(progress: EmbeddingProgress) {
  for (const listener of listeners) listener(progress);
}

function downloadProgress(value: unknown) {
  if (!value || typeof value !== "object") return;
  const progress = value as { status?: string; progress?: number; file?: string };
  if (progress.status === "progress") {
    notify({
      message: "무료 검색 모델을 이 기기에 다운로드하고 있습니다.",
      percent: Number.isFinite(progress.progress) ? Math.round(progress.progress!) : undefined,
    });
  } else if (progress.status === "ready") {
    notify({ message: "기기에서 검색 모델을 준비했습니다.", percent: 100 });
  }
}

async function extractor() {
  if (!extractorPromise) {
    extractorPromise = (async () => {
      const { env, pipeline } = await import("@huggingface/transformers");
      // Only model assets are downloaded. Inputs are passed to the local WASM
      // session, never to Hugging Face Inference Providers or another text API.
      env.allowLocalModels = false;
      env.allowRemoteModels = true;
      env.useBrowserCache = true;
      env.backends.onnx.wasm!.numThreads = 1;
      const model = await pipeline("feature-extraction", LOCAL_EMBEDDING_MODEL.model_id, {
        revision: LOCAL_EMBEDDING_MODEL.revision,
        dtype: LOCAL_EMBEDDING_MODEL.dtype,
        device: "wasm",
        progress_callback: downloadProgress,
      });
      // v3.8.1 feature extraction always truncates using this tokenizer property.
      // It does not accept max_length as a pipeline-call option.
      model.tokenizer.model_max_length = LOCAL_EMBEDDING_MODEL.max_tokens;
      return model;
    })().catch((error: unknown) => {
      extractorPromise = null;
      throw error;
    });
  }
  return extractorPromise;
}

export function assertLocalEmbeddingProfile(profile: Record<string, unknown>) {
  for (const key of ["model_id", "revision", "dtype", "dimensions", "max_tokens", "max_text_chars"] as const) {
    if (profile[key] !== LOCAL_EMBEDDING_MODEL[key]) {
      throw new Error("검색 모델이 변경되었습니다. 화면을 새로 열고 색인을 다시 만들어 주세요.");
    }
  }
}

export async function embedKorean(
  texts: string[],
  kind: "query" | "passage",
  onProgress?: ProgressListener,
): Promise<number[][]> {
  if (!texts.length) return [];
  if (texts.length > 32) throw new Error("자료는 한 번에 32개까지 처리할 수 있습니다.");
  if (texts.some((text) => !text.trim())) throw new Error("검색할 내용을 입력해 주세요.");
  if (onProgress) listeners.add(onProgress);
  const run = pending.then(async () => {
    const model = await extractor();
    notify({ message: "자료의 의미를 이 기기에서 읽고 있습니다." });
    const vectors: number[][] = [];
    // The API accepts 32 items per page, but a device should not allocate a
    // 32-document attention batch. Keep local model memory bounded separately.
    for (let start = 0; start < texts.length; start += 4) {
      const output = await model(
        texts.slice(start, start + 4).map((text) => `${kind}: ${text.slice(0, LOCAL_EMBEDDING_MODEL.max_text_chars)}`),
        { pooling: "mean", normalize: true },
      );
      vectors.push(...output.tolist() as number[][]);
      notify({ message: `자료의 의미를 이 기기에서 읽었습니다 · ${Math.min(start + 4, texts.length)} / ${texts.length}` });
    }
    if (vectors.length !== texts.length || vectors.some((vector) =>
      vector.length !== LOCAL_EMBEDDING_MODEL.dimensions || vector.some((value) => !Number.isFinite(value)),
    )) throw new Error("검색 모델의 출력 형식을 확인할 수 없습니다.");
    return vectors;
  });
  pending = run.catch(() => undefined);
  try {
    return await run;
  } finally {
    if (onProgress) listeners.delete(onProgress);
  }
}

export async function disposeKoreanEmbeddings() {
  await pending;
  const current = extractorPromise;
  extractorPromise = null;
  if (current) {
    try { await (await current).dispose(); } catch { /* Failed model initialization owns no usable session. */ }
  }
  listeners.clear();
}
