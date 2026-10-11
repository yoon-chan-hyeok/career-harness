"use client";

import { FormEvent, useContext, useEffect, useState } from "react";
import type { Artifact } from "./workroom";
import { EditorSaveContext } from "./editor-dialog";

type Citation = { source_id: string; quote: string };
type Statement = { statement: string; citation: Citation };
type Hypothesis = { text: string; confidence: string; citations: Citation[] };
type Extraction = {
  company_facts: Statement[];
  role_signals: Statement[];
  historical_jd_signals: Statement[];
  selection_process_signals: Statement[];
  inferences: Hypothesis[];
};
type Source = {
  id: string;
  title: string;
  url: string;
  published_at: string | null;
  retrieved_at: string;
};
type SourceDocument = {
  text: string;
  category: string;
  freshness: string;
  collection_method: string;
};
const categories = {
  CURRENT_JD: "현재 공고",
  COMPANY: "회사·사업·조직",
  ROLE: "팀·직무·현직자 자료",
  HISTORICAL_JD: "과거·경력·유사 공고",
  EXTERNAL: "외부 자료",
};
const statementFields = {
  company_facts: "회사 사실",
  role_signals: "실제 직무 업무",
  historical_jd_signals: "과거·유사 직무의 신호",
  selection_process_signals: "현재 전형 정보",
};

export function ResearchPanel({
  research,
  review,
  jd,
  ai,
  act,
  editable,
}: {
  research?: Artifact;
  review?: Artifact;
  jd: string;
  ai: boolean;
  act: (action: string, body: object) => Promise<unknown>;
  editable: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [method, setMethod] = useState("PASTE");
  const [decisionMode, setDecisionMode] = useState("INSUFFICIENT");
  const [citationCount, setCitationCount] = useState(1);
  const [confirmed, setConfirmed] = useState(false);
  useEffect(() => setConfirmed(false), [research?.id]);
  const editor = useContext(EditorSaveContext);
  const sources = (research?.data.sources || []) as Source[];
  const documents = (research?.data.source_documents || {}) as Record<
    string,
    SourceDocument
  >;
  const options = [
    { id: "USER_SUPPLIED_JD", title: "등록한 현재 공고", text: jd },
    ...sources
      .filter((source) => documents[source.id])
      .map((source) => ({ ...source, text: documents[source.id].text })),
  ];
  const currentReview =
    review?.status === "LOCKED" && review.data.research_id === research?.id
      ? review
      : undefined;
  const enabled = editable && !busy;
  const execute = async (
    action: string,
    body: object,
    form?: HTMLFormElement,
  ) => {
    if (!enabled) return;
    setBusy(true);
    setError("");
    setMessage("");
    const saved = form ? editor.beginSave(form) : undefined;
    try {
      await act(action, body);
      saved?.();
      setMessage(
        action === "research-confirm"
          ? "현재 자료에 대한 확인을 저장했습니다. 직무 분석을 이어가세요."
          : "조사 자료를 저장했습니다. 현재 출처로 채용 배경을 다시 확인해 주세요.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "조사 자료를 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  const collect = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    void execute(
      "research-source",
      {
        research_id: research?.id || null,
        source_id: values.get("research-source-id") || null,
        method,
        url: values.get("research-url") || "",
        title: values.get("research-title") || "",
        text: method === "PASTE" ? values.get("research-text") || "" : "",
        category: values.get("research-category"),
        published_at: values.get("research-date") || null,
        freshness: values.get("research-freshness"),
      },
      form,
    );
  };
  const addStatement = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const field = String(
      values.get("research-statement-field"),
    ) as keyof typeof statementFields;
    const previous = research?.data.extraction_citations as
      Extraction | undefined;
    const manual: Extraction = {
      company_facts: [],
      role_signals: [],
      historical_jd_signals: [],
      selection_process_signals: [],
      inferences: [],
      ...previous,
    };
    manual[field] = [
      ...manual[field],
      {
        statement: String(values.get("research-statement")),
        citation: {
          source_id: String(values.get("research-statement-source")),
          quote: String(values.get("research-statement-quote")),
        },
      },
    ];
    void execute(
      "research-extract",
      { research_id: research?.id, manual },
      form,
    );
  };
  const confirm = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const citations: Citation[] = [];
    if (decisionMode === "HYPOTHESIS") {
      for (let i = 0; i < citationCount; i++) {
        const source_id = String(values.get(`why-source-${i}`) || "");
        const quote = String(values.get(`why-quote-${i}`) || "");
        if (source_id || quote.trim()) citations.push({ source_id, quote });
      }
    }
    void execute(
      "research-confirm",
      {
        research_id: research?.id,
        mode: decisionMode,
        hypothesis:
          decisionMode === "HYPOTHESIS"
            ? values.get("why-hypothesis") || ""
            : "",
        confidence:
          decisionMode === "HYPOTHESIS" ? values.get("why-confidence") : "LOW",
        limitation: values.get("why-limitation"),
        citations,
        confirmed: values.get("why-confirmed") === "on",
      },
      form,
    );
  };
  return (
    <section className="research-panel" aria-label="회사 조사·채용 배경 확인">
      <h3>회사 조사·채용 배경 확인</h3>
      <p className="muted">
        현재 공고 → 회사·조직 → 실제 업무 → 과거·유사 공고를 확인한 뒤, 왜 지금
        이 역할을 뽑는지 정리합니다. 확인하지 못한 정보는 빈칸으로 남겨도
        됩니다.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {message && (
        <p role="status" className="note">
          {message}
        </p>
      )}
      {!research && (
        <button
          type="button"
          disabled={!enabled}
          onClick={() => void execute("research", { live: ai })}
        >
          조사 시작
        </button>
      )}
      <details>
        <summary>1. 링크·원문 추가 ({sources.length}/12)</summary>
        <p>
          공개 HTTPS 페이지를 가져오거나 본문을 붙여 넣으세요.
          로그인·스크립트·PDF로만 제공되는 자료는 필요한 텍스트를 옮겨 주세요.
          링크 수집에는 AI 키가 필요하지 않습니다.
        </p>
        <form onSubmit={collect}>
          <fieldset disabled={!enabled}>
            <label>
              추가 또는 수정할 자료
              <select name="research-source-id" defaultValue="">
                <option value="">새 자료 추가</option>
                {sources
                  .filter((source) => documents[source.id])
                  .map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.title} 수정
                    </option>
                  ))}
              </select>
            </label>
            <label>
              가져오는 방법
              <select
                name="research-method"
                value={method}
                onChange={(event) => setMethod(event.target.value)}
              >
                <option value="PASTE">본문 붙여 넣기</option>
                <option value="URL">공개 링크에서 가져오기</option>
              </select>
            </label>
            <label>
              자료 분류
              <select name="research-category" defaultValue="COMPANY">
                {Object.entries(categories).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              자료 제목
              <input
                name="research-title"
                required={method === "PASTE"}
                maxLength={300}
              />
            </label>
            <label>
              출처 주소{method === "PASTE" && " (선택)"}
              <input
                name="research-url"
                type="url"
                required={method === "URL"}
                placeholder="https://"
                maxLength={2048}
              />
            </label>
            {method === "PASTE" && (
              <label>
                공개 자료 원문
                <textarea
                  name="research-text"
                  required
                  minLength={20}
                  maxLength={20000}
                  rows={5}
                />
              </label>
            )}
            <div className="grid">
              <label>
                게시일 (모르면 비워 두세요)
                <input name="research-date" type="date" />
              </label>
              <label>
                내용의 시점
                <select name="research-freshness" defaultValue="UNKNOWN">
                  <option value="UNKNOWN">현재 유효한지 확인하지 않음</option>
                  <option value="CURRENT">현재 유효함을 직접 확인</option>
                  <option value="DATED">과거 시점 자료</option>
                </select>
              </label>
            </div>
            <button type="submit">자료 원문 저장</button>
          </fieldset>
        </form>
      </details>
      <details>
        <summary>등록한 원문과 출처 보기</summary>
        {options.map((source) => (
          <details key={source.id} className="research-source">
            <summary>{source.title}</summary>
            {source.id !== "USER_SUPPLIED_JD" && (
              <p className="muted">
                {
                  categories[
                    documents[source.id].category as keyof typeof categories
                  ]
                }{" "}
                · 게시일{" "}
                {sources.find((item) => item.id === source.id)?.published_at ||
                  "미확인"}{" "}
                · 가져온 날짜{" "}
                {sources
                  .find((item) => item.id === source.id)
                  ?.retrieved_at.slice(0, 10)}{" "}
                ·{" "}
                {documents[source.id].collection_method === "URL"
                  ? "공개 페이지에서 수집"
                  : "직접 붙여 넣음"}
              </p>
            )}
            {"url" in source && /^https:\/\//.test(source.url) && (
              <a href={source.url} target="_blank" rel="noreferrer">
                출처 열기
              </a>
            )}
            <pre>{source.text}</pre>
          </details>
        ))}
        {sources
          .filter((source) => !documents[source.id])
          .map((source) => (
            <p key={source.id}>
              {source.title} — 이전 방식으로 등록한 출처입니다. 원문을 추가하면
              정확한 구절을 인용할 수 있습니다.
            </p>
          ))}
      </details>
      <details>
        <summary>2. 자료에서 사실·직무 정보 정리</summary>
        <p>
          모든 정리에는 원문 인용이 필요합니다. 과거 공고는 현재 요건과
          분리하며, 채용 배경은 추론으로만 보관합니다.
        </p>
        {ai && (
          <button
            type="button"
            disabled={!enabled || !Object.keys(documents).length}
            onClick={() =>
              void execute("research-extract", { research_id: research?.id })
            }
          >
            연결한 AI로 자료 정리
          </button>
        )}
        <form onSubmit={addStatement}>
          <fieldset disabled={!enabled || !Object.keys(documents).length}>
            <label>
              정리할 정보
              <select name="research-statement-field">
                {Object.entries(statementFields).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              출처에서 확인한 내용
              <textarea
                name="research-statement"
                required
                minLength={4}
                maxLength={1500}
              />
            </label>
            <label>
              연결할 원문
              <select name="research-statement-source" required>
                <option value="">원문 선택</option>
                {options.map((source) => (
                  <option key={source.id} value={source.id}>
                    {source.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              근거 구절 그대로 인용
              <textarea
                name="research-statement-quote"
                required
                minLength={4}
                maxLength={4000}
              />
            </label>
            <button type="submit">인용과 함께 정보 추가</button>
          </fieldset>
        </form>
      </details>
      <details open={!currentReview}>
        <summary>
          3. 채용 배경·조사 범위 확인{" "}
          {currentReview ? "· 저장됨" : "· 확인 필요"}
        </summary>
        {currentReview && (
          <p className="note">
            {currentReview.data.mode === "HYPOTHESIS"
              ? `공개 근거에 따른 가설: ${currentReview.data.hypothesis}`
              : "자료 부족을 기록하고 확인된 정보로 진행합니다."}
            <br />
            한계: {String(currentReview.data.limitation)}
          </p>
        )}
        {review && !currentReview && (
          <p className="note">
            자료 버전이 바뀌어 이전 확인을 다시 검토해야 합니다.
          </p>
        )}
        {((research?.data.why_now_proposals || []) as Hypothesis[]).map(
          (proposal, i) => (
            <details key={i}>
              <summary>AI가 제안한 가설 (확인 전)</summary>
              <p>{proposal.text}</p>
              {proposal.citations.map((citation, j) => (
                <blockquote key={j}>
                  {
                    options.find((source) => source.id === citation.source_id)
                      ?.title
                  }
                  : {citation.quote}
                </blockquote>
              ))}
            </details>
          ),
        )}
        <form
          onSubmit={confirm}
          onChange={(event) => {
            if (event.target.getAttribute("name") !== "why-confirmed")
              setConfirmed(false);
          }}
        >
          <fieldset disabled={!enabled || !research}>
            <label>
              채용 배경 판단
              <select
                name="why-mode"
                value={decisionMode}
                onChange={(event) => setDecisionMode(event.target.value)}
              >
                <option value="INSUFFICIENT">
                  자료 부족 — 확인된 정보만으로 진행
                </option>
                <option value="HYPOTHESIS">공개 근거에 따른 가설 확인</option>
              </select>
            </label>
            {decisionMode === "HYPOTHESIS" && (
              <>
                <label>
                  지금 이 역할이 필요한 이유 (가설)
                  <textarea
                    name="why-hypothesis"
                    required
                    minLength={8}
                    maxLength={2000}
                  />
                </label>
                <label>
                  가설의 확실성
                  <select name="why-confidence" defaultValue="LOW">
                    <option value="LOW">낮음</option>
                    <option value="MEDIUM">보통</option>
                    <option value="HIGH">높음</option>
                  </select>
                </label>
                {Array.from({ length: citationCount }, (_, i) => (
                  <div key={i} className="review-citation">
                    <label>
                      가설 근거 {i + 1}
                      <select name={`why-source-${i}`} required={i === 0}>
                        <option value="">원문 선택</option>
                        {options.map((source) => (
                          <option key={source.id} value={source.id}>
                            {source.title}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      가설을 뒷받침하는 구절 {i + 1}
                      <textarea
                        name={`why-quote-${i}`}
                        required={i === 0}
                        maxLength={4000}
                      />
                    </label>
                  </div>
                ))}
                {citationCount < 8 && (
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setCitationCount((value) => value + 1)}
                  >
                    가설 근거 추가
                  </button>
                )}
              </>
            )}
            <label>
              아직 확인하지 못한 정보·가설의 한계
              <textarea
                name="why-limitation"
                required
                minLength={8}
                maxLength={3000}
                placeholder="어떤 자료가 없거나, 어떤 부분이 추론인지 적어 주세요."
              />
            </label>
            <label className="check">
              <input
                type="checkbox"
                name="why-confirmed"
                required
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              현재 출처와 한계를 읽었으며, 가설은 회사의 확정 사실이 아님을
              확인했습니다.
            </label>
            <button type="submit">채용 배경·조사 범위 확인 저장</button>
          </fieldset>
        </form>
      </details>
    </section>
  );
}
