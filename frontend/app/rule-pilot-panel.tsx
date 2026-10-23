"use client";

import { useCallback, useEffect, useState } from "react";
import type { Request } from "./api-client";

type ProofState = {
  current: boolean;
  id: string;
  data: {
    status?: string;
    activation?: string;
    checks_executed?: number;
    rule_version?: number;
  };
} | null;
type Rule = {
  rule_id: string;
  summary: string;
  source_package: string;
  candidate_52: boolean;
  unrefined_65: boolean;
  proof: string | null;
  excerpt: string | null;
  issue: string | null;
  contract: {
    version: number;
    action: string;
    gate: string;
    scope: string;
    start_line: number;
    end_line: number;
  } | null;
  states: {
    RuleSourceReview: ProofState;
    RuleCodeEvaluation: ProofState;
    RuleActivation: ProofState;
  };
};
type Catalog = {
  revision: string;
  availability: string;
  workspace_id: string;
  rules: Rule[];
  counts: { indexed: number; candidate_52: number; unrefined_65: number };
  unavailable_adoptions: { rule_id: string; rule_version: number }[];
};
const actions: Record<string, string> = {
  CHECK_METRICS: "근거 안의 수치·범위 확인",
  CHECK_OWNERSHIP: "본인 수행 범위 확인",
  CHECK_LENGTH: "현재 글자 수 확인",
};

export function RulePilotPanel({
  workspaceId,
  revisionKey,
  request,
  onSaved,
  disabled = false,
}: {
  workspaceId: string;
  revisionKey: string;
  request: Request;
  onSaved: () => Promise<void>;
  disabled?: boolean;
}) {
  const [data, setData] = useState<Catalog | null>(null);
  const [selected, setSelected] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const path = `/v4/applications/${workspaceId}/rules`;
  const load = useCallback(async () => {
    const next: Catalog = await request(path);
    if (next.workspace_id !== workspaceId)
      throw new Error("지원 작업을 다시 확인해 주세요.");
    return next;
  }, [request, path, workspaceId]);
  useEffect(() => {
    let active = true;
    load()
      .then((next) => {
        if (active) {
          setData(next);
          setConfirmed(false);
        }
      })
      .catch((cause) => {
        if (active && cause?.status !== 404)
          setError(
            cause instanceof Error
              ? cause.message
              : "규칙 검토를 불러오지 못했습니다.",
          );
      });
    return () => {
      active = false;
    };
  }, [load, revisionKey]);
  const act = async (action: string, ruleId: string, version: number) => {
    if (!data || !confirmed) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await request(`${path}/${action}`, {
        expected_revision: data.revision,
        rule_id: ruleId,
        rule_version: version,
        confirmed: true,
      });
      setData(await load());
      setConfirmed(false);
      await onSaved();
      setNotice(
        action === "evaluate"
          ? "실제 코드 검증 결과를 저장했습니다. AI 글쓰기 평가·기존 20회귀 실행과 별개입니다."
          : "요청한 확인·승인·중단을 기록했습니다.",
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "현재 출처와 버전을 다시 확인해 주세요.",
      );
    } finally {
      setBusy(false);
    }
  };
  if (!data) return error ? <p role="alert">{error}</p> : null;
  const row = data.rules.find((r) => r.rule_id === selected);
  const reviewed = row?.states.RuleSourceReview?.current;
  const evaluated =
    row?.states.RuleCodeEvaluation?.current &&
    row.states.RuleCodeEvaluation.data.status === "PASSED";
  const adopted =
    row?.states.RuleActivation?.data.activation === "ACTIVE_SCOPED";
  return (
    <details className="rule-pilot-panel writing-plan-panel">
      <summary>
        규칙 원문·검증 검토 <small>개인 파일럿</small>
      </summary>
      <p>
        인덱스 {data.counts.indexed}개 · 미승인 보정 {data.counts.candidate_52}
        개 · 미정밀화 {data.counts.unrefined_65}개
      </p>
      <p>
        인덱스는 참고 후보입니다. 원문 대조·실제 코드 검증·적용 범위 승인은 각각
        필요합니다. 공용 배포나 전체 규칙 승인이 아닙니다.
      </p>
      {data.availability !== "CONFIGURED" && (
        <p>
          원문·인덱스 연결이{" "}
          {data.availability === "EMPTY"
            ? "아직 준비되지 않았습니다."
            : "유효하지 않습니다. 파일 연결을 확인해 주세요."}
        </p>
      )}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      <label>
        검토할 규칙
        <select
          aria-label="검토할 규칙"
          value={selected}
          disabled={busy || disabled}
          onChange={(e) => {
            setSelected(e.target.value);
            setConfirmed(false);
            setNotice("");
          }}
        >
          <option value="">규칙을 선택하세요</option>
          {data.rules.map((r) => (
            <option key={r.rule_id} value={r.rule_id}>
              {r.rule_id} · {r.summary.slice(0, 50)}
            </option>
          ))}
        </select>
      </label>
      {row && (
        <section>
          <p>{row.summary}</p>
          <small>
            출처 표기: {row.source_package} · 인덱스만으로 원문 일치를 인증하지
            않습니다.
          </small>
          {row.issue && <p role="status">{row.issue}</p>}
          {row.contract && (
            <p>
              이 지원서의{" "}
              {row.contract.scope === "RESUME" ? "이력서" : "자소서"} ·{" "}
              {actions[row.contract.action] || row.contract.action} · 원문{" "}
              {row.contract.start_line}~{row.contract.end_line}행
            </p>
          )}
          {row.excerpt ? (
            <blockquote>{row.excerpt}</blockquote>
          ) : (
            <p>
              직접 대조할 원문 구간과 실행 계약이 필요합니다. 현재 활성화할 수
              없습니다.
            </p>
          )}
          <p>
            출처 연결: {reviewed ? "이번 버전 직접 확인" : "확인 전"} · 코드
            검증:{" "}
            {evaluated
              ? "통과"
              : row.states.RuleCodeEvaluation?.data.status === "FAILED"
                ? "실패"
                : "통과 증거 없음"}{" "}
            · 적용:{" "}
            {adopted
              ? row.states.RuleActivation?.current
                ? "이 지원서에서 채택"
                : "재확인 필요"
              : "비활성"}
          </p>
          <label>
            <input
              type="checkbox"
              aria-label="출처와 범위 직접 확인"
              checked={confirmed}
              disabled={busy || disabled}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            원문·실행 조건·현재 검증 결과와 이 지원서의 적용 범위를 직접 읽고
            확인했습니다.
          </label>
          <div className="writing-plan-actions">
            <button
              type="button"
              disabled={
                busy || disabled || !confirmed || !row.proof || !row.contract
              }
              onClick={() =>
                void act("source-review", row.rule_id, row.contract!.version)
              }
            >
              원문·규칙 연결 확인
            </button>
            <button
              type="button"
              disabled={
                busy || disabled || !confirmed || !reviewed || !row.contract
              }
              onClick={() =>
                void act("evaluate", row.rule_id, row.contract!.version)
              }
            >
              준비한 코드 사례 실행
            </button>
            <button
              type="button"
              disabled={
                busy ||
                disabled ||
                !confirmed ||
                !evaluated ||
                !row.contract ||
                !!adopted
              }
              onClick={() =>
                void act("activate", row.rule_id, row.contract!.version)
              }
            >
              이 지원서에 적용 승인
            </button>
            <button
              type="button"
              disabled={
                busy ||
                disabled ||
                !confirmed ||
                !adopted ||
                !row.states.RuleActivation?.data.rule_version
              }
              onClick={() =>
                void act(
                  "retire",
                  row.rule_id,
                  row.states.RuleActivation!.data.rule_version!,
                )
              }
            >
              규칙 사용 중단
            </button>
          </div>
        </section>
      )}
      {data.unavailable_adoptions.map((old) => (
        <div key={old.rule_id}>
          <p>
            {old.rule_id}: 채택했던 출처를 확인할 수 없어 문서 검수를
            보류합니다.
          </p>
          <label>
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(e) => setConfirmed(e.target.checked)}
              disabled={busy || disabled}
            />
            이 규칙의 사용 중단을 확인합니다.
          </label>
          <button
            type="button"
            disabled={busy || disabled || !confirmed}
            onClick={() => void act("retire", old.rule_id, old.rule_version)}
          >
            연결 끊긴 규칙 사용 중단
          </button>
        </div>
      ))}
      <p className="muted">
        미승인 52개·미정밀화 65개는 적용 대상에서 제외합니다. 설계된 25개
        게이트·과거 연결 사례 20개·실제 AI 평가를 이번 코드 검증 통과로 표시하지
        않습니다. 채택 후 현재 문서 검수에서 실제 실행 기록을 남깁니다.
      </p>
    </details>
  );
}
