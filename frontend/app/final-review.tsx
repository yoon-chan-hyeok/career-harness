"use client";
import { FormEvent, useContext, useEffect, useState } from "react";
import { EditorSaveContext } from "./editor-dialog";
import type { Artifact } from "./page";

type Context = {
  context_hash: string;
  base_profession: string;
  actual_outputs: string[];
  assignment_statement: string;
  fatal_gaps: string[];
  selection_risks: string[];
  evidence: { id: string; title: string; body: string }[];
  documents: { id: string; kind: string; version: number; text: string }[];
  previous: Artifact | null;
  current_pass: boolean;
};
type Props = {
  workspaceId: string;
  revision: string;
  frozen: boolean;
  request: <T>(path: string, body?: object, method?: string) => Promise<T>;
  act: (action: string, body: object) => Promise<unknown>;
};
export function FinalReview({
  workspaceId,
  revision,
  frozen,
  request,
  act,
}: Props) {
  const [data, setData] = useState<Context | null>(null),
    [error, setError] = useState("");
  const [busy, setBusy] = useState(false),
    [confirmed, setConfirmed] = useState(false);
  const editor = useContext(EditorSaveContext);
  useEffect(() => {
    let active = true;
    setConfirmed(false);
    request<Context>(`/applications/${workspaceId}/final-review-context`)
      .then((result) => {
        if (active) {
          setData(result);
          setError("");
        }
      })
      .catch((reason) => {
        if (active) {
          setData(null);
          setError(
            reason instanceof Error
              ? reason.message
              : "최종 확인 자료를 불러오지 못했습니다.",
          );
        }
      });
    return () => {
      active = false;
    };
  }, [workspaceId, revision, request]);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!data || busy || frozen) return;
    const form = event.currentTarget,
      values = new FormData(form),
      done = editor.beginSave(form);
    setBusy(true);
    setError("");
    try {
      await act("final-review", {
        context_hash: data.context_hash,
        role_noun: values.get("final-role"),
        role_alignment: values.get("final-alignment"),
        assignment_answer: values.get("final-assignment"),
        motivation_answer: values.get("final-motivation"),
        wants_core_work: values.get("final-intent") === "YES",
        evidence_answer: values.get("final-evidence-answer"),
        citations: [
          {
            evidence_id: values.get("final-evidence"),
            quote: values.get("final-quote"),
          },
        ],
        gaps_answer: values.get("final-gaps"),
        decision: values.get("final-decision"),
        return_stage: values.get("final-return"),
        confirmed,
      });
      done();
      setConfirmed(false);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "최종 확인을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  const prior = data?.previous?.data;
  const citations = prior?.citations as
    { evidence_id: string; quote: string }[] | undefined;
  return (
    <section
      className="final-review-panel"
      aria-label="직업 정체성·마지막 세 질문"
    >
      <h3>직업 정체성과 마지막 세 질문</h3>
      <p className="muted">
        최종 문서를 읽고 직접 답해 주세요. 지원 의향은 AI가 대신 결정하지
        않습니다. 문서·전략·근거가 바뀌면 다시 확인합니다.
      </p>
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {data && (
        <>
          <p className="note">
            {data.current_pass
              ? "현재 문서에 대한 최종 확인 완료. 전체 검수를 거쳐 보관할 수 있습니다."
              : "현재 문서에 대한 직접 확인이 필요합니다."}
          </p>
          <dl>
            <dt>분석한 본업</dt>
            <dd>{data.base_profession}</dd>
            <dt>맡길 업무</dt>
            <dd>{data.assignment_statement}</dd>
            <dt>실제 산출물</dt>
            <dd>{data.actual_outputs.join(" · ")}</dd>
            <dt>남은 공백·위험</dt>
            <dd>
              {[...data.fatal_gaps, ...data.selection_risks].join(" · ") ||
                "현재 전략에 등록한 공백이 없습니다. 누락 여부를 직접 살펴주세요."}
            </dd>
          </dl>
          <details>
            <summary>잠근 문서·현재 근거 읽기</summary>
            {data.documents.map((doc) => (
              <article key={doc.id}>
                <strong>
                  {doc.kind === "Draft" ? "자소서" : "이력서"} · v{doc.version}
                </strong>
                <pre>{doc.text}</pre>
              </article>
            ))}
            {data.evidence.map((e) => (
              <article key={e.id}>
                <strong>{e.title}</strong>
                <pre>{e.body}</pre>
              </article>
            ))}
          </details>
          {frozen ? (
            <p>
              이미 보관한 최종본입니다. 당시 확인 기록은 보관본에 유지됩니다.
            </p>
          ) : (
            <form
              key={data.context_hash}
              onSubmit={save}
              onChange={(event) => {
                if (event.target.getAttribute("name") !== "final-confirmed")
                  setConfirmed(false);
              }}
            >
              <fieldset disabled={busy}>
                <label>
                  문서를 읽고 가장 먼저 떠오르는 직업 명칭
                  <input
                    name="final-role"
                    required
                    minLength={2}
                    maxLength={120}
                    defaultValue={String(prior?.role_noun || "")}
                  />
                </label>
                <label>
                  분석한 본업과 일치하는가
                  <select name="final-alignment" required defaultValue="">
                    <option value="">직접 판단하세요</option>
                    <option value="MATCH">일치함</option>
                    <option value="MISMATCH">다르게 읽힘</option>
                    <option value="UNCERTAIN">판단이 어려움</option>
                  </select>
                </label>
                <label>
                  1. 채용되면 어떤 일을 맡길 수 있는가
                  <textarea
                    name="final-assignment"
                    required
                    minLength={15}
                    maxLength={2000}
                    defaultValue={String(prior?.assignment_answer || "")}
                  />
                </label>
                <label>
                  2. 이 직무·조직의 본업을 하고 싶은 이유
                  <textarea
                    name="final-motivation"
                    required
                    minLength={15}
                    maxLength={2000}
                    defaultValue={String(prior?.motivation_answer || "")}
                  />
                </label>
                <label>
                  현재 본업 지원 의향
                  <select name="final-intent" required defaultValue="">
                    <option value="">현재 의향을 선택하세요</option>
                    <option value="YES">이 본업을 하고 싶음</option>
                    <option value="NO">아직 확신이 없거나 원하지 않음</option>
                  </select>
                </label>
                <label>
                  3. 이 경험이 그 일을 잘할 근거가 되는 이유
                  <textarea
                    name="final-evidence-answer"
                    required
                    minLength={15}
                    maxLength={2000}
                    defaultValue={String(prior?.evidence_answer || "")}
                  />
                </label>
                <label>
                  답변을 뒷받침하는 현재 경험
                  <select
                    name="final-evidence"
                    required
                    defaultValue={citations?.[0]?.evidence_id || ""}
                  >
                    <option value="">선택하세요</option>
                    {data.evidence.map((e) => (
                      <option key={e.id} value={e.id}>
                        {e.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  근거 원문에서 그대로 인용
                  <textarea
                    name="final-quote"
                    required
                    minLength={4}
                    maxLength={2000}
                    defaultValue={citations?.[0]?.quote || ""}
                  />
                </label>
                <label>
                  아직 증명하지 못한 범위와 받아들일 공백
                  <textarea
                    name="final-gaps"
                    required
                    minLength={8}
                    maxLength={2000}
                    defaultValue={String(prior?.gaps_answer || "")}
                  />
                </label>
                <label>
                  최종 판단
                  <select name="final-decision" required defaultValue="">
                    <option value="">판단을 선택하세요</option>
                    <option value="PASS">세 질문에 답할 수 있음</option>
                    <option value="REVISE">먼저 보완해야 함</option>
                  </select>
                </label>
                <label>
                  돌아가서 보완할 단계
                  <select name="final-return" defaultValue="NONE">
                    <option value="NONE">보완할 단계 없음</option>
                    <option value="ANALYSIS">직무 분석</option>
                    <option value="STRATEGY">지원 전략</option>
                    <option value="EVIDENCE">경험·근거</option>
                    <option value="WRITING">문항·이력서 작성</option>
                  </select>
                </label>
                <label className="check">
                  <input
                    type="checkbox"
                    name="final-confirmed"
                    required
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  현재 문서·근거와 제 지원 의향을 직접 확인했습니다.
                </label>
                <button type="submit">마지막 세 질문 확인 저장</button>
              </fieldset>
            </form>
          )}
        </>
      )}
    </section>
  );
}
