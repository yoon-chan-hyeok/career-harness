"use client";
import { FormEvent, useContext, useEffect, useState } from "react";
import { EditorSaveContext } from "./editor-dialog";
import type { Artifact, Workspace } from "./page";

type Request = (path: string, body?: unknown, method?: string) => Promise<any>; // eslint-disable-line @typescript-eslint/no-explicit-any
type Reference = {
  id: string;
  title: string;
  version: string;
  active: boolean;
  role: string;
};

export function OpportunityRankings({
  request,
  open,
}: {
  request: Request;
  open: (id: string) => void;
}) {
  type Ranked = {
    workspace_id: string;
    company: string;
    role: string;
    fit: string;
    career_value: string;
    action_priority: string;
  };
  const [data, setData] = useState<{
    fit_order: Ranked[];
    action_order: Ranked[];
  }>({ fit_order: [], action_order: [] });
  useEffect(() => {
    let live = true;
    request("/opportunities/rankings")
      .then((r) => {
        if (live) setData(r);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [request]);
  const level: Record<string, string> = {
    HIGH: "높음",
    MEDIUM: "보통",
    LOW: "낮음",
    UNKNOWN: "확인 필요",
  };
  return data.fit_order.length ? (
    <section>
      <h3>지원할 가치와 오늘 할 일</h3>
      <p className="muted">
        저장한 평가를 기준으로 따로 정렬합니다. 마감이 가까워도 직무
        적합도·커리어 가치는 바뀌지 않습니다.
      </p>
      <div className="ranking-columns">
        {(
          [
            ["fit_order", "직무 적합도 우선"],
            ["action_order", "오늘 행동 순서"],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <h4>{label}</h4>
            {data[key].map((row, index) => (
              <button
                className="ranking-item"
                key={row.workspace_id}
                onClick={() => open(row.workspace_id)}
              >
                <span>{index + 1}</span>
                <div>
                  <strong>
                    {row.company} · {row.role}
                  </strong>
                  <small>
                    적합도 {level[row.fit]} · 커리어 가치{" "}
                    {level[row.career_value]} · 행동 우선{" "}
                    {level[row.action_priority]}
                  </small>
                </div>
              </button>
            ))}
          </div>
        ))}
      </div>
    </section>
  ) : null;
}

export function FactConflictReview({
  request,
  refresh,
}: {
  request: Request;
  refresh: () => Promise<void>;
}) {
  type Conflict = {
    id: string;
    key: string;
    value: Record<string, unknown>;
    source_title: string;
  };
  const [rows, setRows] = useState<Conflict[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    request("/fact-conflicts")
      .then((r) => {
        if (live) setRows(r);
      })
      .catch(() => {
        if (live) setError("사실 충돌을 불러오지 못했습니다.");
      });
    return () => {
      live = false;
    };
  }, [request]);
  return rows.length || error ? (
    <section>
      <h3>직접 대조할 사실 충돌</h3>
      <p className="muted">
        최근 정정과 기존 측정값이 다르면 둘 다 사용을 멈춥니다. 출처를 대조해
        사용할 값을 선택하세요. 관련 경험 원문도 새 값과 맞게 정리해 주세요.
      </p>
      {rows.map((r) => (
        <div className="mapping" key={r.id}>
          <strong>{r.key}</strong>
          <p>{Object.values(r.value).map(String).join(" · ")}</p>
          <small>출처: {r.source_title}</small>
          <button
            className="secondary"
            onClick={() =>
              void request(`/fact-conflicts/${r.id}/resolve`, {
                confirmed: true,
              })
                .then(async () => {
                  setRows(await request("/fact-conflicts"));
                  await refresh();
                })
                .catch((e) => setError(e.message))
            }
          >
            이 값과 출처를 확인했음 · 사용
          </button>
        </div>
      ))}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  ) : null;
}
type Proposal = {
  id: string;
  data: {
    status: string;
    version: number;
    before: string;
    after: string;
    patch: { old_text: string; new_text: string };
  };
};

export function ReferenceSettings({
  request,
  refresh,
}: {
  request: Request;
  refresh: () => Promise<void>;
}) {
  const [rows, setRows] = useState<Reference[]>([]),
    [content, setContent] = useState(""),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    request("/references")
      .then((r) => {
        if (live) setRows(r);
      })
      .catch(() => {
        if (live) setError("추가 자료를 불러오지 못했습니다.");
      });
    return () => {
      live = false;
    };
  }, [request]);
  return (
    <section className="reference-settings">
      <h3>추가 작성 기준</h3>
      <p className="muted">
        작업 단계에 필요한 기준만 적용합니다. 표현 예시·과거 수치는 사실 근거로
        등록되지 않습니다.
      </p>
      {rows.filter((r) => r.active).length === 0 && (
        <p>아직 사용 중인 추가 자료가 없습니다.</p>
      )}
      {rows.map((r) => (
        <div className="reference-row" key={r.id}>
          <div>
            <strong>{r.title}</strong>
            <small>
              {r.version} · {r.active ? "사용 중" : "보관 중"}
            </small>
          </div>
          <button
            className="secondary"
            onClick={() =>
              void request(`/references/${r.id}`)
                .then((v) => setContent(v.data.content))
                .catch((e) => setError(e.message))
            }
          >
            원문 보기
          </button>
          <button
            className="secondary"
            onClick={() =>
              void request(`/references/${r.id}/activation`, {
                active: !r.active,
              })
                .then(async () => {
                  setRows(await request("/references"));
                  await refresh();
                })
                .catch((e) => setError(e.message))
            }
          >
            {r.active ? "사용 중지" : "다시 사용"}
          </button>
        </div>
      ))}
      {content && (
        <details open>
          <summary>추가 자료 원문</summary>
          <pre className="reference-original">{content}</pre>
          <button className="secondary" onClick={() => setContent("")}>
            닫기
          </button>
        </details>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}

function RevisionCard({
  proposal: p,
  request,
  workspace,
  refresh,
  reload,
}: {
  proposal: Proposal;
  request: Request;
  workspace: string;
  refresh: () => Promise<void>;
  reload: () => Promise<void>;
}) {
  const [text, setText] = useState(p.data.patch.new_text),
    [checked, setChecked] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const editorSave = useContext(EditorSaveContext);
  const fieldName = `revision_text_${p.id}`;
  const decide = async (decision: string) => {
    const saved = editorSave.beginNames([fieldName]);
    setBusy(true);
    setError("");
    try {
      await request(`/applications/${workspace}/revision-proposals/${p.id}`, {
        decision,
        ...(decision === "ACCEPT" ? { new_text: text } : {}),
      });
      await refresh();
      await reload();
      saved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "제안을 처리하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="revision-card">
      <h4>수정 제안 · 원문 v{p.data.version}</h4>
      <div className="revision-before">
        <small>수정할 원문</small>
        <pre>{p.data.patch.old_text}</pre>
      </div>
      <label>
        반영할 문장
        <textarea
          name={fieldName}
          disabled={busy}
          value={text}
          onChange={(e) => {
            setText(e.target.value);
            setChecked(false);
          }}
        />
      </label>
      <details>
        <summary>전체 문장 비교</summary>
        <small>원문</small>
        <pre>{p.data.before}</pre>
        <small>제안된 전체 본문</small>
        <pre>{p.data.before.replace(p.data.patch.old_text, text)}</pre>
      </details>
      <label className="check">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => setChecked(e.target.checked)}
        />
        문장·근거·수행 범위를 확인했습니다.
      </label>
      <div className="row">
        <button
          disabled={!checked || busy}
          onClick={() => void decide("ACCEPT")}
        >
          확인한 수정 반영
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void decide("REJECT")}
        >
          거절 · 원문 유지
        </button>
      </div>
      <p className="muted">
        직접 고친 문장은 근거를 다시 확인합니다. 반영 후 검수와 최종 잠금이
        필요합니다.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function RevisionInbox({
  workspace,
  request,
  refresh,
  reloadKey,
}: {
  workspace: Workspace;
  request: Request;
  refresh: () => Promise<void>;
  reloadKey?: number;
}) {
  const [rows, setRows] = useState<Proposal[]>([]),
    [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    request(`/applications/${workspace.id}/revision-proposals`)
      .then((r) => {
        if (live) setRows(r);
      })
      .catch(() => {
        if (live) setError("수정 제안을 불러오지 못했습니다.");
      });
    return () => {
      live = false;
    };
  }, [request, workspace, reloadKey]);
  const reload = async () =>
    setRows(await request(`/applications/${workspace.id}/revision-proposals`));
  const pending = rows.filter((r) => r.data.status === "PENDING");
  return pending.length || error ? (
    <section className="revision-inbox">
      <h3>
        내 확인을 기다리는 수정 <span>{pending.length}</span>
      </h3>
      {pending.map((p) => (
        <RevisionCard
          key={p.id}
          proposal={p}
          workspace={workspace.id}
          request={request}
          refresh={refresh}
          reload={reload}
        />
      ))}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </section>
  ) : null;
}

export function AssessmentDecision({
  artifact,
  workspace,
  request,
  refresh,
}: {
  artifact: Artifact;
  workspace: string;
  request: Request;
  refresh: () => Promise<void>;
}) {
  const [error, setError] = useState(""),
    [done, setDone] = useState("");
  return (
    <div className="assessment-decision">
      <p>추천을 검토한 뒤 내 행동을 결정하세요.</p>
      <div className="row">
        {[
          ["PROCEED", "지원하기"],
          ["HOLD", "보류하기"],
          ["SKIP", "건너뛰기"],
        ].map(([decision, label]) => (
          <button
            className="secondary"
            key={decision}
            onClick={() =>
              void request(
                `/applications/${workspace}/actions/decide-opportunity`,
                { artifact_id: artifact.id, decision },
              )
                .then(async () => {
                  setDone(label + " · 결정 저장됨");
                  await refresh();
                })
                .catch((e) => setError(e.message))
            }
          >
            {label}
          </button>
        ))}
      </div>
      {done && <p role="status">{done}</p>}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

export function AssessmentEditor({
  workspace: w,
  request,
  refresh,
  ai,
}: {
  workspace: Workspace;
  request: Request;
  refresh: () => Promise<void>;
  ai: boolean;
}) {
  const [profile, setProfile] = useState<Record<string, unknown>>({}),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let live = true;
    request("/profile")
      .then((p) => {
        if (live) setProfile(p);
      })
      .catch(() => {
        if (live) setError("확인된 프로필을 불러오지 못했습니다.");
      });
    return () => {
      live = false;
    };
  }, [request]);
  const opportunity = w.artifacts
    .filter((a) => a.kind === "OpportunityBrief")
    .sort((a, b) => b.version - a.version)[0];
  const required = (opportunity?.data.required || []) as {
    requirement: string;
  }[];
  const companySources = (w.artifacts
    .filter((a) => a.kind === "CompanyResearchResult")
    .sort((a, b) => b.version - a.version)[0]?.data.sources || []) as {
    id: string;
    title: string;
  }[];
  const editorSave = useContext(EditorSaveContext);
  const save = async (manual?: unknown, saved?: () => void) => {
    setBusy(true);
    setError("");
    try {
      await request(
        `/applications/${w.id}/actions/assess-opportunity`,
        manual ? { manual } : {},
      );
      await refresh();
      saved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "평가를 저장하지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  const submit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const get = (k: string) => String(f.get(k) || "");
    const saved = editorSave.beginSave(e.currentTarget);
    void save(
      {
        eligibility: required.map((r, i) => ({
          requirement: r.requirement,
          status: get("status" + i),
          reason: get("reason" + i),
          profile_keys: get("key" + i) ? [get("key" + i)] : [],
        })),
        ...Object.fromEntries(
          ["fit", "career_value", "action_priority"].map((axis) => [
            axis,
            {
              level: get(axis),
              reason: get(axis + "_reason"),
              source_ids: get(axis + "_source")
                .split("\n")
                .map((s) => s.trim())
                .filter(Boolean),
            },
          ]),
        ),
        selection_risks: get("risks").split("\n").filter(Boolean),
        preparation_cost: get("cost"),
        recommendation: get("recommendation"),
        main_fix: get("fix"),
      },
      saved,
    );
  };
  return (
    <details className="panel">
      <summary>지원 자격·가치·행동 순서 검토</summary>
      <div className="panel-body">
        <p className="muted">
          적합도와 커리어 가치, 오늘 할 일을 나눠 봅니다. 필수 조건이 불명확하면
          확인 필요로 남겨 주세요.
        </p>
        {ai && (
          <button disabled={busy} onClick={() => void save()}>
            AI 추천 만들기
          </button>
        )}
        <form onSubmit={submit}>
          {required.map((r, i) => (
            <div className="mapping" key={r.requirement}>
              <strong>{r.requirement}</strong>
              <label>
                자격 확인
                <select name={"status" + i} defaultValue="NEEDS_VERIFICATION">
                  <option value="NEEDS_VERIFICATION">확인 필요</option>
                  <option value="MET">충족</option>
                  <option value="NOT_MET">미충족</option>
                </select>
              </label>
              <label>
                확인된 프로필 근거
                <select name={"key" + i}>
                  <option value="">근거 미확인</option>
                  {Object.keys(profile).map((k) => (
                    <option key={k} value={k}>
                      {k}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                판단 이유
                <input name={"reason" + i} />
              </label>
            </div>
          ))}
          {[
            ["fit", "직무 적합도"],
            ["career_value", "커리어 가치"],
            ["action_priority", "지금 행동 순서"],
          ].map(([axis, label]) => (
            <div className="mapping" key={axis}>
              <label>
                {label}
                <select name={axis} defaultValue="UNKNOWN">
                  <option value="UNKNOWN">확인 필요</option>
                  <option value="HIGH">높음</option>
                  <option value="MEDIUM">보통</option>
                  <option value="LOW">낮음</option>
                </select>
              </label>
              <label>
                판단 이유
                <textarea name={axis + "_reason"} />
              </label>
              <label>
                판단 근거 출처
                <select
                  name={axis + "_source"}
                  defaultValue={axis === "career_value" ? "" : "jd"}
                >
                  <option value="">출처 미확인</option>
                  <option value="jd">등록한 공고</option>
                  {companySources.map((source) => (
                    <option key={source.id} value={source.id}>
                      {source.title}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ))}
          <label>
            전형 위험
            <textarea name="risks" />
          </label>
          <label>
            준비 비용
            <select name="cost">
              <option value="UNKNOWN">확인 필요</option>
              <option value="NOW">지금 지원 가능</option>
              <option value="SHORT">1~3일 보완</option>
              <option value="MEDIUM">1~3주 준비</option>
              <option value="HIGH">장기 준비</option>
            </select>
          </label>
          <label>
            추천
            <select name="recommendation">
              <option value="LOW_PRIORITY">우선순위 낮음</option>
              <option value="PROCEED">지원 추천</option>
              <option value="PROCEED_WITH_GAP">공백을 인정하고 지원</option>
              <option value="SKIP">건너뛰기 추천</option>
            </select>
          </label>
          <label>
            가장 중요한 보완점
            <textarea name="fix" />
          </label>
          <button disabled={busy || !opportunity}>검토 저장</button>
        </form>
        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}
      </div>
    </details>
  );
}
