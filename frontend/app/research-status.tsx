import type { Artifact } from "./page";

export function ResearchStatus({
  research,
  review,
  onOpen,
}: {
  research?: Artifact;
  review?: Artifact;
  onOpen?: () => void;
}) {
  const scope = research?.data.scope;
  const details =
    scope && typeof scope === "object" && !Array.isArray(scope) ? scope : null;
  const confirmed =
    review?.status === "LOCKED" && review.data.research_id === research?.id;
  const missing = (
    Array.isArray(details?.missing_information)
      ? details.missing_information
      : []
  ).filter(
    (value) =>
      !(
        confirmed &&
        review.data.mode === "HYPOTHESIS" &&
        String(value).includes("Why Now")
      ),
  );
  return (
    <section className="note" aria-label="회사 조사 범위">
      <strong>
        {details?.basis === "JD_ONLY"
          ? "공고 자료로 진행 중"
          : "회사 조사 범위 확인"}
      </strong>
      <p>
        {typeof details?.summary === "string"
          ? details.summary
          : "회사 자료의 출처와 최신성을 확인해 주세요. 조사 기록이 없으면 공고만으로 분석하며 회사 사실을 임의로 채우지 않습니다."}
      </p>
      {research && !["ACTIVE", "LOCKED"].includes(research.status) && (
        <p>조사 자료가 바뀌었습니다. 현재 자료로 다시 분석해 주세요.</p>
      )}
      {missing.length > 0 && (
        <p>확인할 자료: {missing.map(String).join(" · ")}</p>
      )}
      <p>
        {confirmed
          ? review.data.mode === "HYPOTHESIS"
            ? "채용 배경 가설을 확인했습니다. 회사의 확정 사실과 구분해 사용합니다."
            : "자료 부족을 직접 확인했습니다. 확인된 정보 범위로 진행합니다."
          : "채용 배경과 부족한 자료를 직접 확인해야 합니다."}
      </p>
      {onOpen && (
        <button type="button" className="secondary" onClick={onOpen}>
          회사 조사·채용 배경 확인
        </button>
      )}
    </section>
  );
}
