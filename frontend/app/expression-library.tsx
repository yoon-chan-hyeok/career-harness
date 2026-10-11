"use client";

import { FormEvent, useContext, useEffect, useState } from "react";
import type { Artifact } from "./workroom";
import { EditorSaveContext } from "./editor-dialog";

type Pattern = { id: string; label: string; text: string };
type Library = { patterns: Pattern[]; expressions: Artifact[] };
type Props = {
  document?: Artifact;
  domain: "COVER" | "RESUME";
  workspaceId: string;
  request: <T>(path: string, body?: object, method?: string) => Promise<T>;
  act: (action: string, body: object) => Promise<unknown>;
  evidence: { id: string; title: string }[];
};
const logicOptions = [
  "상황",
  "제약",
  "관찰",
  "판단",
  "대안",
  "행동",
  "산출물",
  "검증",
  "업무 가치",
  "한계",
  "배운 점",
  "직무 연결",
];
const toneOptions = [
  "짧은 문장",
  "담백함",
  "설명 중심",
  "판단 먼저",
  "산출물 먼저",
];

export function ExpressionLibrary({
  document,
  domain,
  workspaceId,
  request,
  act,
  evidence,
}: Props) {
  const [library, setLibrary] = useState<Library | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [scope, setScope] = useState("QUESTION_TYPE");
  const [pattern, setPattern] = useState("JUDGMENT_FIRST");
  const [confirmed, setConfirmed] = useState(false);
  const [message, setMessage] = useState("");
  const editor = useContext(EditorSaveContext);
  const documentId = document?.id;
  useEffect(() => {
    let active = true;
    setConfirmed(false);
    request<Library>("/expressions")
      .then((result) => {
        if (active) {
          setLibrary(result);
          setError("");
        }
      })
      .catch((reason) => {
        if (active)
          setError(
            reason instanceof Error
              ? reason.message
              : "표현 보관함을 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, [request, workspaceId, documentId, reload]);
  const save = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (busy || document?.status !== "LOCKED") return;
    const form = event.currentTarget;
    const values = new FormData(form);
    setBusy(true);
    setError("");
    setMessage("");
    const saved = editor.beginSave(form);
    try {
      await act("expression-save", {
        document_id: document.id,
        excerpt: String(values.get("expression-excerpt") || ""),
        pattern_ids: [pattern],
        logic_pattern: [0, 1, 2, 3]
          .map((i) => values.get(`expression-logic-${i}`))
          .filter(Boolean),
        tone_tags: values.getAll("expression-tone"),
        scope,
        evidence_id:
          scope === "PROJECT" ? values.get("expression-evidence") : null,
        allow_grounded_excerpt: values.get("expression-original") === "on",
        confirmed,
      });
      saved();
      setConfirmed(false);
      setReload((value) => value + 1);
      setMessage(
        "표현을 보관했습니다. 다음 작성에서 선택한 범위와 현재 근거를 확인해 참고합니다.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "표현을 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  const toggle = async (entry: Artifact) => {
    setBusy(true);
    setError("");
    try {
      await request(
        `/expressions/${entry.id}`,
        { active: !entry.data.active },
        "PATCH",
      );
      setReload((value) => value + 1);
      setMessage(
        entry.data.active
          ? "다음 작성부터 이 표현을 사용하지 않습니다. 기존 문서는 그대로 보존됩니다."
          : "다음 작성에서 이 표현을 다시 참고합니다.",
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "표현 사용 설정을 바꾸지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  const entries =
    library?.expressions.filter((entry) => entry.data.domain === domain) || [];
  return (
    <section className="expression-library" aria-label="내 표현 보관함">
      <h3>내 표현 보관함</h3>
      <p className="muted">
        직접 고른 문장과 논리 구조를 보관합니다. 원문의 회사명·날짜·수치는 새
        사실로 등록되지 않습니다.
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
      {!library && <p className="muted">표현 보관함을 불러오는 중입니다.</p>}
      {document?.status === "LOCKED" && library ? (
        <details>
          <summary>이 문서의 표현 저장</summary>
          <details>
            <summary>잠근 현재 문서 보기</summary>
            <pre>{String(document.data.text)}</pre>
          </details>
          <form
            key={document.id}
            onSubmit={save}
            onChange={(event) => {
              if (event.target.getAttribute("name") !== "expression-confirmed")
                setConfirmed(false);
            }}
          >
            <fieldset disabled={busy}>
              <label>
                보관할 원문 구절
                <textarea
                  name="expression-excerpt"
                  required
                  minLength={4}
                  maxLength={2000}
                  placeholder="현재 문서에서 마음에 드는 구절을 그대로 옮겨 주세요."
                />
              </label>
              <label>
                재사용할 표현 구조
                <select
                  name="expression-pattern"
                  value={pattern}
                  onChange={(event) => setPattern(event.target.value)}
                >
                  {library.patterns.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label}
                    </option>
                  ))}
                </select>
              </label>
              <p className="note">
                {library.patterns.find((item) => item.id === pattern)?.text}
                <br />
                빈칸에는 다음 지원서에서 선택한 현재 근거를 사용합니다.
              </p>
              <div className="expression-logic">
                {["관찰", "판단", "행동", "검증"].map((value, i) => (
                  <label key={i}>
                    논리 순서 {i + 1}
                    <select name={`expression-logic-${i}`} defaultValue={value}>
                      <option value="">생략</option>
                      {logicOptions.map((label) => (
                        <option key={label} value={label}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
              </div>
              <fieldset className="expression-tones">
                <legend>유지할 말투 (1~3개)</legend>
                {toneOptions.map((label) => (
                  <label key={label} className="check">
                    <input
                      type="checkbox"
                      name="expression-tone"
                      value={label}
                      defaultChecked={label === "담백함"}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              <label>
                사용할 범위
                <select
                  name="expression-scope"
                  value={scope}
                  onChange={(event) => setScope(event.target.value)}
                >
                  <option value="QUESTION_TYPE">같은 문항 유형</option>
                  <option value="PROJECT">같은 프로젝트 근거</option>
                  <option value="DOMAIN">
                    모든 {domain === "COVER" ? "자소서" : "이력서"}
                  </option>
                </select>
              </label>
              {scope === "PROJECT" && (
                <label>
                  프로젝트 근거
                  <select name="expression-evidence" required>
                    <option value="">선택하세요</option>
                    {evidence
                      .filter((entry) =>
                        (
                          (document.data.selected_evidence_ids ||
                            []) as string[]
                        ).includes(entry.id),
                      )
                      .map((entry) => (
                        <option key={entry.id} value={entry.id}>
                          {entry.title}
                        </option>
                      ))}
                  </select>
                </label>
              )}
              <label className="check">
                <input type="checkbox" name="expression-original" />
                원문 문장도 참고 허용 — 현재 선택한 근거로 다시 검증될 때만 전달
              </label>
              <p className="muted">
                원문을 허용해도 기여·수치·주장 한계가 바뀌거나 다른 경험을
                선택하면 문장 구조만 참고합니다. 회사·프로필 사실이 포함된
                원문은 옮기지 않습니다.
              </p>
              <label className="check">
                <input
                  name="expression-confirmed"
                  type="checkbox"
                  required
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
                원문과 재사용 범위를 읽고 이 표현을 승인합니다.
              </label>
              <button type="submit">표현 승인·저장</button>
            </fieldset>
          </form>
        </details>
      ) : (
        <p className="muted">
          검수를 마치고 문서를 최종 잠그면 마음에 드는 표현을 저장할 수
          있습니다.
        </p>
      )}
      <details>
        <summary>
          저장한 {domain === "COVER" ? "자소서" : "이력서"} 표현 (
          {entries.length})
        </summary>
        {!entries.length && (
          <p className="muted">아직 승인한 표현이 없습니다.</p>
        )}
        {entries.map((entry) => (
          <article key={entry.id} className="expression-entry">
            <p>
              <strong>
                {entry.data.active ? "다음 작성에 사용" : "사용 중지"}
              </strong>{" "}
              ·{" "}
              {entry.data.scope === "PROJECT"
                ? "같은 프로젝트 근거"
                : entry.data.scope === "QUESTION_TYPE"
                  ? "같은 문항 유형"
                  : "문서 종류 전체"}
            </p>
            <p>{((entry.data.logic_pattern || []) as string[]).join(" → ")}</p>
            {((entry.data.pattern_ids || []) as string[]).map((id) => (
              <p key={id}>
                {library?.patterns.find((item) => item.id === id)?.text}
              </p>
            ))}
            <details>
              <summary>보관한 원문 (이전 문서)</summary>
              <blockquote>{String(entry.data.excerpt)}</blockquote>
              <p className="muted">
                이 구절을 저장했다는 이유만으로 현재 사실이 되지는 않습니다.
              </p>
            </details>
            <button
              className="secondary"
              type="button"
              disabled={busy}
              onClick={() => void toggle(entry)}
            >
              {entry.data.active ? "표현 사용 중지" : "표현 다시 사용"}
            </button>
          </article>
        ))}
      </details>
    </section>
  );
}
