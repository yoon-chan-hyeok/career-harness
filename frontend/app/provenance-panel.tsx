"use client";
import { useEffect, useState } from "react";
import type { Request } from "./api-client";

type RecordData = Record<string, unknown>;
const records = (value: unknown): RecordData[] =>
  Array.isArray(value)
    ? (value.filter((item) => item && typeof item === "object") as RecordData[])
    : [];
const show = (value: unknown): string =>
  value === null || value === undefined
    ? "미기록"
    : typeof value === "object"
      ? Array.isArray(value)
        ? value.map(show).join(" · ")
        : Object.entries(value)
            .map(([key, item]) => `${labels[key] || key}: ${show(item)}`)
            .join("\n")
      : String(value);
const labels: Record<string, string> = {
  USER: "직접 수행",
  USER_AI_ASSISTED: "AI 보조를 받아 직접 수행",
  USER_MODIFIED_EXISTING_CODE: "기존 코드를 수정해 수행",
  TEAM: "팀 수행",
  LAB: "연구실 수행",
  UNKNOWN: "확인 필요",
  SUPPORTED: "근거 연결",
  PARTIAL: "부분 근거",
  PARTIALLY_SUPPORTED: "부분 근거",
  NEEDS_REVIEW: "확인 필요",
  UNMAPPED: "주장 연결 미기록",
  UNSUPPORTED: "근거 미충족",
  FACT: "경험·사실",
  COMPANY_FACT: "회사·직무 사실",
  INTERPRETATION: "해석",
  ownership: "수행 범위",
  implementation: "구현",
  problem_definition: "문제 정의",
  hypothesis: "가설",
  experiment_design: "실험 설계",
  integration: "통합",
  result_scope: "결과 범위",
  name: "지표",
  value: "측정값",
  unit: "단위",
  baseline: "비교 기준",
  sample: "표본",
  sample_size: "표본 크기",
  measurement_context: "측정 환경",
  measured_at: "측정 시점",
  business_effect: "업무 성과 여부",
  status: "확인 상태",
  USER_CONFIRMED: "직접 확인",
  SOURCE_BACKED: "원자료 근거 있음",
  VERIFIED: "검증 완료",
  UNVERIFIED: "미검증",
  key: "프로필 항목",
  quote: "원문 인용",
  STALE: "이전 근거로 작성됨",
  SUPERSEDED: "이전 버전",
  DO_NOT_USE: "사용 중단",
  INVALID: "사용 불가",
};
function Detail({ data }: { data: RecordData }) {
  const value =
    data.data && typeof data.data === "object"
      ? { ...(data.data as RecordData), status: data.status }
      : data;
  return (
    <dl className="provenance-details">
      {Object.entries(value)
        .filter(
          ([key]) =>
            ![
              "id",
              "source_id",
              "evidence_id",
              "user_id",
              "created_at",
              "updated_at",
              "title",
              "body",
              "text",
              "source",
              "sources",
              "ownership",
              "metrics",
            ].includes(key),
        )
        .map(([key, value]) => (
          <div key={key}>
            <dt>{labels[key] || key}</dt>
            <dd>{labels[String(value)] || show(value)}</dd>
          </div>
        ))}
    </dl>
  );
}
function Source({ source }: { source: RecordData }) {
  const url =
    typeof source.url === "string" && /^https?:\/\//.test(source.url)
      ? source.url
      : "";
  return (
    <div className="source-quote">
      <strong>
        {show(
          source.title ||
            source.filename ||
            (String(source.path || "").startsWith("uploads/")
              ? "업로드 원자료"
              : String(source.path || "원자료").replace(/^manual\//, "")),
        )}
      </strong>
      {url && (
        <a href={url} target="_blank" rel="noreferrer">
          출처 열기 ↗
        </a>
      )}
      {source.quote ? (
        <blockquote>{show(source.quote)}</blockquote>
      ) : source.body ? (
        <details>
          <summary>원자료 내용</summary>
          <pre>{show(source.body)}</pre>
        </details>
      ) : (
        <p className="muted">연결된 출처의 원문 인용이 없습니다.</p>
      )}
      <p className="muted">
        출처 상태 · {labels[String(source.status)] || "확인 필요"}
      </p>
    </div>
  );
}
export function ProvenancePanel({
  artifactId,
  request,
}: {
  artifactId: string;
  request: Request;
}) {
  const [opened, setOpened] = useState(false);
  const [claims, setClaims] = useState<RecordData[]>([]);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    if (!opened) return;
    let active = true;
    setBusy(true);
    setError("");
    request(`/artifacts/${artifactId}/provenance`)
      .then((data) => {
        if (active) {
          setClaims(records(data.items));
          setSelected(0);
        }
      })
      .catch((error) => {
        if (active)
          setError(
            error instanceof Error
              ? error.message
              : "근거를 불러오지 못했습니다.",
          );
      })
      .finally(() => {
        if (active) setBusy(false);
      });
    return () => {
      active = false;
    };
  }, [artifactId, opened, request]);
  const claim = claims[selected];
  return (
    <details
      className="provenance-panel"
      onToggle={(event) => setOpened(event.currentTarget.open)}
    >
      <summary>문장별 근거 확인</summary>
      {busy && <p role="status">문장과 원자료의 연결을 확인하고 있어요…</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!busy && !error && opened && !claims.length && (
        <p className="muted">
          이 버전에는 연결된 주장 기록이 없습니다. 본문과 근거 연결을 다시
          확인해 주세요.
        </p>
      )}
      {claims.length > 0 && (
        <>
          <div
            className="claim-list"
            role="group"
            aria-label="근거를 확인할 문장"
          >
            {claims.map((item, index) => (
              <button
                className={index === selected ? "active" : "secondary"}
                key={index}
                onClick={() => setSelected(index)}
              >
                <small>
                  {index + 1}번 문장 ·{" "}
                  {labels[String(item.type)] || String(item.type || "주장")}
                </small>
                {show(item.text)}
              </button>
            ))}
          </div>
          {claim && (
            <div className="claim-detail">
              <blockquote>{show(claim.text)}</blockquote>
              <p>
                <span className="badge">
                  {labels[String(claim.support)] || "지원 범위 미기록"}
                </span>{" "}
                주장에 기록된 수행 범위:{" "}
                {claim.ownership_ok === true
                  ? "확인됨"
                  : claim.ownership_ok === false
                    ? "재확인 필요"
                    : "미기록"}
              </p>
              {records(claim.evidence).map((evidence, index) => (
                <article
                  key={String(evidence.id || index)}
                  className="linked-evidence"
                >
                  <h4>{show(evidence.title || "연결 경험")}</h4>
                  <span className="badge">
                    {labels[String(evidence.status)] || show(evidence.status)}
                  </span>
                  {Boolean(evidence.body) && (
                    <details>
                      <summary>경험 원문</summary>
                      <pre>{show(evidence.body)}</pre>
                    </details>
                  )}
                  {Boolean(evidence.source) &&
                    typeof evidence.source === "object" && (
                      <Source source={evidence.source as RecordData} />
                    )}
                </article>
              ))}
              {records(claim.metrics).length > 0 && (
                <div>
                  <h5>이 문장이 사용하는 지표</h5>
                  {records(claim.metrics).map((metric, index) => (
                    <Detail key={index} data={metric} />
                  ))}
                </div>
              )}
              <div>
                <h5>연결된 경험의 본인 수행 범위</h5>
                {records(claim.ownership).length ? (
                  records(claim.ownership).map((ownership, index) => (
                    <Detail key={index} data={ownership} />
                  ))
                ) : (
                  <p className="muted">
                    별도 수행 범위 기록이 없습니다. 원자료에서 확인해 주세요.
                  </p>
                )}
              </div>
              {records(claim.company_sources).length > 0 && (
                <div>
                  <h5>회사·직무 출처</h5>
                  <p className="muted">
                    회사 자료의 사실입니다. 본인의 수행 경험 근거와 구분해
                    확인하세요.
                  </p>
                  {records(claim.company_sources).map((source, index) => (
                    <Source key={index} source={source} />
                  ))}
                </div>
              )}
              {records(claim.profile_facts).length > 0 && (
                <div>
                  <h5>내 프로필 사실</h5>
                  {records(claim.profile_facts).map((fact, index) => (
                    <Detail key={index} data={fact} />
                  ))}
                </div>
              )}
              {records(claim.missing_links).length > 0 && (
                <p className="error">
                  일부 연결 자료를 찾지 못했습니다. 철회되었거나 현재 계정에
                  없는 자료가 포함되어 있습니다.
                </p>
              )}
              {!records(claim.evidence).length &&
                !records(claim.company_sources).length &&
                !records(claim.profile_facts).length && (
                  <p className="muted">
                    이 문장과 직접 연결된 자료가 없습니다. 유사한 경험을
                    자동으로 근거로 표시하지 않습니다.
                  </p>
                )}
            </div>
          )}
        </>
      )}
    </details>
  );
}
