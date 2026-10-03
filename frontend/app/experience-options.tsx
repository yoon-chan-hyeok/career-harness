"use client";

import { useCallback, useEffect, useState } from "react";
import type { Request } from "./api-client";

type ExperienceOption = {
  rank: number;
  evidence_id: string;
  title: string;
  source_ids: string[];
  sources?: { id: string; title: string; status: string }[];
  classification: string;
  recommendation_reason: string;
  strengths: string[];
  gaps: string[];
  recommended: boolean;
  used_in_slots: string[];
  usage_count: number;
};
type Options = {
  workspace_id: string;
  slot: string;
  base_artifact_id: string | null;
  base_artifact_version: number | null;
  options_revision: string;
  options: ExperienceOption[];
  selected_evidence_id: string | null;
  selection_status: string | null;
  inherited_from?: string | null;
  notice: string;
};
const fitLabels: Record<string, string> = {
  DIRECT: "직접 근거",
  ADJACENT: "인접 경험",
  TRANSFERABLE: "전이 가능 경험",
};

export function ExperienceOptions({
  workspaceId,
  slot,
  version,
  request,
  sourceNames,
  slotNames,
  onSelected,
  ready = true,
}: {
  workspaceId: string;
  slot: string;
  version: string;
  request: Request;
  sourceNames: Record<string, string>;
  slotNames: Record<string, string>;
  onSelected: (evidenceId: string) => Promise<void>;
  ready?: boolean;
}) {
  const [data, setData] = useState<Options | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [selecting, setSelecting] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const load = useCallback(
    () =>
      request(
        `/applications/${workspaceId}/experience-options?slot=${encodeURIComponent(slot)}`,
      ) as Promise<Options>,
    [request, workspaceId, slot],
  );
  useEffect(() => {
    let active = true;
    setData(null);
    setError("");
    setNotice("");
    if (!ready) {
      setLoading(false);
      return () => {
        active = false;
      };
    }
    setLoading(true);
    load()
      .then((result) => {
        if (result.workspace_id !== workspaceId || result.slot !== slot)
          throw new Error("선택 대상이 바뀌었습니다. 다시 불러와 주세요.");
        if (active) setData(result);
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : "글감을 불러오지 못했습니다.",
          );
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [load, workspaceId, slot, version, refreshKey, ready]);

  async function select(option: ExperienceOption) {
    if (!data || selecting) return;
    setSelecting(option.evidence_id);
    setError("");
    setNotice("");
    try {
      const result = await request(
        `/applications/${workspaceId}/experience-options/select`,
        {
          slot,
          evidence_id: option.evidence_id,
          base_artifact_id: data.base_artifact_id,
          base_artifact_version: data.base_artifact_version,
          options_revision: data.options_revision,
        },
      );
      await onSelected(option.evidence_id);
      const updated = await load();
      setData(updated);
      setNotice(
        result.next_step ||
          "선택을 저장했습니다. 다음 설계에 반영하고 내용을 읽은 뒤 승인하세요.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "선택을 저장하지 못했습니다.",
      );
    } finally {
      setSelecting("");
    }
  }

  return (
    <section className="experience-options" aria-label="경험 글감 추천">
      <div className="experience-options-heading">
        <div>
          <span className="eyebrow">START WITH YOUR PROOF</span>
          <h3>이 글에는 어떤 경험을 쓸까요?</h3>
        </div>
        <button
          className="text-button"
          disabled={loading || !!selecting}
          aria-label="경험 추천 새로고침"
          onClick={() => setRefreshKey((key) => key + 1)}
        >
          ↻
        </button>
      </div>
      <p className="experience-options-target">
        {slot === "strategy"
          ? "지원 직무 · 전략"
          : slot === "resume"
            ? "이력서 · 첫 경험"
            : slotNames[slot] || "선택한 문항"}
      </p>
      {loading && (
        <p role="status">확인된 경험과 직무 근거를 연결하고 있어요.</p>
      )}
      {!ready && (
        <div className="experience-options-empty">
          직무 분석과 경험·근거 연결을 먼저 확인해 주세요. 확인된 근거가
          준비되면 최대 3안의 글감을 추천합니다.
        </div>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="note" role="status">
          {notice}
        </p>
      )}
      {data && (
        <>
          <p className="experience-options-notice">{data.notice}</p>
          {data.inherited_from === "strategy" &&
            data.selection_status !== "STALE" && (
              <p className="note">
                지원 전략에서 선택한 경험을 이어받았습니다. 이 글의 경험을 따로
                선택할 수도 있어요.
              </p>
            )}
          {data.selection_status === "STALE" && (
            <p className="experience-gaps" role="status">
              이전에 선택한 경험의 근거가 바뀌었습니다. 현재 추천을 확인하고
              다시 선택해 주세요.
            </p>
          )}
          {data.options.length ? (
            <div className="experience-option-list">
              {data.options.slice(0, 3).map((option, index) => {
                const chosen = data.selected_evidence_id === option.evidence_id;
                return (
                  <article
                    key={option.evidence_id}
                    className={`experience-option ${chosen ? "experience-option-selected" : ""}`}
                  >
                    <div className="experience-option-top">
                      <span>{index + 1}안</span>
                      {option.recommended && (
                        <span className="experience-recommended">추천 1</span>
                      )}
                      <small>
                        {fitLabels[option.classification] || "근거 검토 필요"}
                      </small>
                    </div>
                    <h4>{option.title}</h4>
                    <p>{option.recommendation_reason}</p>
                    {!!option.strengths.length && (
                      <ul className="experience-strengths">
                        {option.strengths.map((strength, i) => (
                          <li key={i}>{strength}</li>
                        ))}
                      </ul>
                    )}
                    <div className="experience-proof">
                      <strong>실제 근거</strong>
                      <span>{option.title}</span>
                      {option.source_ids.map((id) => (
                        <small key={id}>
                          {option.sources?.find((source) => source.id === id)
                            ?.title ||
                            sourceNames[id] ||
                            "연결된 원자료"}
                        </small>
                      ))}
                    </div>
                    {!!option.gaps.length && (
                      <div className="experience-gaps">
                        <strong>확인할 점</strong>
                        {option.gaps.map((gap, i) => (
                          <p key={i}>{gap}</p>
                        ))}
                      </div>
                    )}
                    {option.usage_count > 0 && (
                      <p className="experience-reuse">
                        다른 글에서 {option.usage_count}회 사용 ·{" "}
                        {option.used_in_slots
                          .map(
                            (used) =>
                              slotNames[used] ||
                              (used === "resume" ? "이력서" : "지원 전략"),
                          )
                          .join(" · ")}
                      </p>
                    )}
                    <button
                      className={chosen ? "secondary" : ""}
                      disabled={
                        !!selecting ||
                        (chosen &&
                          data.selection_status !== "STALE" &&
                          !data.inherited_from)
                      }
                      onClick={() => void select(option)}
                    >
                      {selecting === option.evidence_id
                        ? "선택 저장 중…"
                        : chosen && data.selection_status !== "STALE"
                          ? data.inherited_from
                            ? "이 글의 선택으로 저장하기"
                            : "선택됨"
                          : chosen
                            ? "바뀐 근거로 다시 선택"
                            : "이 경험으로 선택하기"}
                    </button>
                    {chosen && data.selection_status === "STALE" && (
                      <small className="experience-gaps">
                        근거가 바뀌어 재선택이 필요합니다.
                      </small>
                    )}
                  </article>
                );
              })}
            </div>
          ) : (
            <div className="experience-options-empty">
              추천할 만큼 확인된 근거가 아직 없습니다. 경험을 확인하고 직무와
              연결한 뒤 다시 살펴보세요.
            </div>
          )}
          {data.options.length > 0 && data.options.length < 3 && (
            <p className="experience-options-caption">
              현재 확인된 근거로 {data.options.length}안을 추천합니다.
            </p>
          )}
          <p className="experience-options-caption">
            선택은 다음 설계와 문서에 반영됩니다. 승인하려면 바뀐 내용과 근거를
            읽고 확인하세요.
          </p>
        </>
      )}
    </section>
  );
}
