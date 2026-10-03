"use client";
import { useEffect, useRef, useState } from "react";
import type { Request } from "./api-client";

type Document = {
  evidence_id: string;
  title: string;
  text: string;
  content_hash: string;
  indexed: boolean;
};
type Result = {
  id?: string;
  evidence_id?: string;
  title?: string;
  body?: string;
  text?: string;
  score?: number;
};

export function KnowledgeSearch({ request }: { request: Request }) {
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Result[]>([]);
  const profile = useRef("");
  const active = useRef(true);
  const loaded = useRef<typeof import("./korean-embeddings") | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      void loaded.current?.disposeKoreanEmbeddings();
    };
  }, []);
  const model = async () => {
    if (!consent)
      throw new Error(
        "기기에서 사용할 검색 모델 다운로드를 먼저 확인해 주세요.",
      );
    const [data, engine] = await Promise.all([
      request("/semantic/profile"),
      import("./korean-embeddings"),
    ]);
    if (!active.current)
      throw new Error("화면이 바뀌어 검색 준비를 중단했습니다.");
    loaded.current = engine;
    engine.assertLocalEmbeddingProfile(data.profile_info || data);
    profile.current = data.profile_id || data.profile_info?.profile_id;
    return engine;
  };
  const index = async () => {
    setBusy(true);
    setMessage("검색 모델을 준비하고 있어요…");
    setResults([]);
    try {
      const engine = await model();
      let cursor = "";
      let count = 0;
      do {
        const response = await request(
          `/semantic/documents?kind=FACT${cursor ? "&cursor=" + encodeURIComponent(cursor) : ""}`,
        );
        if (!active.current) return;
        const items: Document[] = response.items.filter(
          (item: Document) => !item.indexed,
        );
        for (let start = 0; start < items.length; start += 32) {
          const batch = items.slice(start, start + 32);
          const vectors = await engine.embedKorean(
            batch.map((item) => item.text),
            "passage",
            (progress) => {
              if (active.current) setMessage(progress.message);
            },
          );
          if (!active.current) return;
          const saved = await request("/semantic/index", {
            profile_id: profile.current,
            items: batch.map((item, index) => ({
              evidence_id: item.evidence_id,
              content_hash: item.content_hash,
              vector: vectors[index],
            })),
          });
          count += Number(saved.indexed || 0);
          setMessage(`${count}개의 경험을 검색할 수 있도록 준비했습니다.`);
        }
        cursor = response.next_cursor || "";
      } while (cursor);
      setMessage(
        `한국어 검색 준비 완료 · 이번에 ${count}개 항목을 반영했습니다.`,
      );
    } catch (error) {
      if (active.current)
        setMessage(
          error instanceof Error
            ? error.message
            : "검색을 준비하지 못했습니다.",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  };
  const search = async () => {
    setBusy(true);
    setMessage("관련 경험을 찾고 있어요…");
    setResults([]);
    try {
      const engine = await model();
      const [vector] = await engine.embedKorean(
        [query],
        "query",
        (progress) => {
          if (active.current) setMessage(progress.message);
        },
      );
      if (!active.current) return;
      const response = await request("/semantic/search", {
        profile_id: profile.current,
        query,
        vector,
        kind: "FACT",
        limit: 12,
      });
      setResults(response.items);
      setMessage(
        response.semantic_used
          ? "입력한 의미와 가까운 경험을 찾았습니다. 결과를 직접 확인해 주세요."
          : "아직 검색을 준비한 경험이 없습니다. 먼저 ‘내 경험 검색 준비’를 실행해 주세요.",
      );
    } catch (error) {
      if (active.current)
        setMessage(
          error instanceof Error
            ? error.message
            : "관련 경험을 찾지 못했습니다.",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  };
  return (
    <section className="knowledge-search">
      <h3>의미로 경험 찾기</h3>
      <p className="muted">
        한국어 문장의 의미로 관련 경험을 찾습니다. 처음 사용할 때 모델·실행 파일
        약 150MB를 내려받고 기기에서 실행합니다. 자료는 외부 AI 제공자에 보내지
        않으며, 만든 검색 벡터를 내 계정에 저장합니다.
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={consent}
          disabled={busy}
          onChange={(event) => setConsent(event.target.checked)}
        />
        기기에서 사용할 검색 모델을 내려받겠습니다.
      </label>
      <button
        className="secondary"
        disabled={busy || !consent}
        onClick={() => void index()}
      >
        내 경험 검색 준비 · 새 자료 반영
      </button>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <label>
          찾고 싶은 경험
          <input
            value={query}
            maxLength={4000}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="예: 제약 속에서 서비스 안정성을 높인 경험"
          />
        </label>
        <button disabled={busy || !consent || !query.trim()}>
          관련 경험 찾기
        </button>
      </form>
      {message && (
        <p role="status" className="note">
          {message}
        </p>
      )}
      {results.map((item, index) => (
        <article className="card" key={item.evidence_id || item.id || index}>
          <h4>{item.title || "관련 경험"}</h4>
          <p>{item.body || item.text}</p>
          <small className="muted">
            관련성은 검색 점수이며 사실 확인이나 직무 적합성 승인을 뜻하지
            않습니다.
          </small>
        </article>
      ))}
    </section>
  );
}

export function SemanticMapping({
  request,
  workspaceId,
  outputs,
  ai,
  refresh,
}: {
  request: Request;
  workspaceId: string;
  outputs: string[];
  ai: boolean;
  refresh: () => Promise<void>;
}) {
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const active = useRef(true);
  const loaded = useRef<typeof import("./korean-embeddings") | null>(null);
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
      void loaded.current?.disposeKoreanEmbeddings();
    };
  }, []);
  const map = async () => {
    setBusy(true);
    setMessage("직무에 연결할 경험을 의미로 찾고 있어요…");
    try {
      const [profile, engine] = await Promise.all([
        request("/semantic/profile"),
        import("./korean-embeddings"),
      ]);
      if (!active.current) return;
      loaded.current = engine;
      engine.assertLocalEmbeddingProfile(profile.profile_info || profile);
      const [vector] = await engine.embedKorean(
        [outputs.join(" ")],
        "query",
        (progress) => {
          if (active.current) setMessage(progress.message);
        },
      );
      if (!active.current) return;
      const ready = await request("/semantic/search", {
        profile_id: profile.profile_id || profile.profile_info?.profile_id,
        query: outputs.join(" "),
        vector,
        kind: "FACT",
        limit: 1,
      });
      if (!active.current) return;
      if (!ready.indexed_count)
        throw new Error(
          "먼저 경험 정리 화면에서 ‘내 경험 검색 준비’를 실행해 주세요.",
        );
      const result = await request(
        `/applications/${workspaceId}/actions/evidence-map`,
        {
          semantic_query_vector: vector,
          semantic_profile_id:
            profile.profile_id || profile.profile_info?.profile_id,
        },
      );
      if (!active.current) return;
      await refresh();
      setMessage(
        result.data?.retrieval_metadata?.semantic_used
          ? "문장의 의미를 활용해 관련 경험을 찾고 직무별 근거를 연결했습니다."
          : "준비된 의미 검색 자료가 부족해 키워드 검색으로 근거를 연결했습니다.",
      );
    } catch (error) {
      if (active.current)
        setMessage(
          error instanceof Error
            ? error.message
            : "근거를 연결하지 못했습니다.",
        );
    } finally {
      if (active.current) setBusy(false);
    }
  };
  return (
    <details className="semantic-mapping">
      <summary>한국어 의미 검색으로 경험 연결</summary>
      <p className="muted">
        경험 정리에서 준비한 검색 자료를 사용합니다. 검색 모델은 이 기기에서
        실행하고, 직무별 근거 분류는 연결한 AI가 확인합니다. 관련성이 높아도
        직접 수행 근거를 자동 승인하지 않습니다.
      </p>
      <label className="check">
        <input
          type="checkbox"
          checked={consent}
          disabled={busy}
          data-draft-ignore
          onChange={(event) => setConsent(event.target.checked)}
        />
        기기에서 검색 모델을 내려받아 사용하겠습니다 (처음 약 150MB).
      </label>
      <button
        disabled={busy || !consent || !ai || !outputs.length}
        onClick={() => void map()}
      >
        의미 검색을 활용해 AI 근거 연결
      </button>
      {!ai && (
        <p className="muted">
          직무별 근거 분류에는 AI 연결이 필요합니다. 의미로 경험 찾기는 경험
          정리 화면에서 먼저 사용할 수 있습니다.
        </p>
      )}
      {message && (
        <p className="note" role="status">
          {message}
        </p>
      )}
    </details>
  );
}
