"use client";
import {
  forwardRef,
  createContext,
  ReactNode,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { Request } from "./api-client";
import {
  draftHasChanges,
  editableDraftFields,
  serializeDraftFields,
} from "./draft-fields";

type FieldValue = { value: string; kind: string };
type Payload = Record<string, FieldValue>;
type Draft = {
  payload: Payload;
  base_artifact_id?: string;
  updated_at: string;
  stale_base?: boolean;
};
export const EditorSaveContext = createContext<{
  beginSave: (form: HTMLFormElement) => () => void;
  beginNames: (names: string[]) => () => void;
}>({
  beginSave: () => () => {},
  beginNames: () => () => {},
});
export type EditorHandle = {
  beforeLeave: (action: () => void) => void;
  beginSave: (form: HTMLFormElement) => () => void;
};

function fields(dialog: HTMLDialogElement) {
  return editableDraftFields(
    Array.from(
      dialog.querySelectorAll<
        HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement
      >(
        "input:not([data-draft-ignore]), textarea:not([data-draft-ignore]), select:not([data-draft-ignore])",
      ),
    ),
  );
}
function snapshot(dialog: HTMLDialogElement): Payload {
  return serializeDraftFields(fields(dialog));
}

function modifiedFields(dialog: HTMLDialogElement | null, baseline: Payload) {
  if (!dialog) return false;
  // Asynchronously loaded forms are initially clean. Compare their actual
  // defaults rather than treating newly visible inputs as user edits.
  const defaults = serializeDraftFields(
    fields(dialog).map((field) => ({
      name: field.name,
      id: field.id,
      type: field.type,
      value:
        field instanceof HTMLSelectElement
          ? (Array.from(field.options).find((option) => option.defaultSelected)
              ?.value ??
            field.options[0]?.value ??
            "")
          : field.defaultValue,
    })),
  );
  return draftHasChanges(snapshot(dialog), baseline, defaults);
}

export const EditorDialog = forwardRef<
  EditorHandle,
  {
    children: ReactNode;
    onClose: () => void;
    request: Request;
    draftKey: string;
    workspaceId: string;
    baseArtifactId?: string;
  }
>(function EditorDialog(
  { children, onClose, request, draftKey, workspaceId, baseArtifactId },
  handle,
) {
  const dialog = useRef<HTMLDialogElement>(null);
  const baseline = useRef<Payload>({});
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastWrite = useRef<Promise<unknown>>(Promise.resolve());
  const leave = useRef<(() => void) | null>(null);
  const [dirty, setDirty] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [draftMessage, setDraftMessage] = useState("");
  const [confirmLeave, setConfirmLeave] = useState(false);
  const path = `/editor-drafts/${encodeURIComponent(draftKey)}`;
  const store = () => {
    if (!dialog.current) return Promise.resolve();
    const payload = snapshot(dialog.current);
    const task = () =>
      request(
        path,
        {
          payload,
          workspace_id: workspaceId,
          base_artifact_id: baseArtifactId || null,
        },
        "PUT",
      );
    lastWrite.current = lastWrite.current.catch(() => {}).then(task);
    return lastWrite.current;
  };
  const guard = (action: () => void) => {
    if (!dirty) {
      action();
      return;
    }
    leave.current = action;
    setConfirmLeave(true);
  };
  const beginSave = (
    match: (
      field: HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement,
    ) => boolean,
  ) => {
    if (!dialog.current) return () => {};
    const saved = snapshot(dialog.current);
    const keys = fields(dialog.current).flatMap((field, index) =>
      match(field) ? [`${index}:${field.name || field.id}`] : [],
    );
    return () => {
      keys.forEach((key) => {
        baseline.current[key] = saved[key];
      });
      const modified = modifiedFields(dialog.current, baseline.current);
      setDirty(modified);
      if (timer.current) clearTimeout(timer.current);
      if (modified)
        void store()
          .then(() =>
            setDraftMessage("입력 중인 다른 내용을 초안으로 보관했습니다."),
          )
          .catch(() => setDraftMessage("나머지 초안은 보관하지 못했습니다."));
      else
        void lastWrite.current
          .catch(() => {})
          .then(() => request(path, undefined, "DELETE"))
          .then(() => {
            setDraft(null);
            setDraftMessage("편집 내용을 문서로 저장했습니다.");
          })
          .catch(() => {});
    };
  };
  useImperativeHandle(handle, () => ({
    beforeLeave: guard,
    beginSave: (form) => beginSave((field) => field.form === form),
  }));
  useEffect(() => {
    dialog.current?.showModal();
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);
  useEffect(() => {
    let active = true;
    if (timer.current) clearTimeout(timer.current);
    baseline.current = dialog.current ? snapshot(dialog.current) : {};
    setDirty(false);
    setConfirmLeave(false);
    setDraft(null);
    setDraftMessage("");
    request(path)
      .then((value: Draft) => {
        if (active) setDraft(value);
      })
      .catch((error) => {
        if (active && error?.status !== 404)
          setDraftMessage(
            "보관 초안을 확인하지 못했습니다. 연결을 확인해 주세요.",
          );
      });
    return () => {
      active = false;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [path, request]);
  useEffect(() => {
    if (!dirty) return;
    const prevent = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", prevent);
    return () => window.removeEventListener("beforeunload", prevent);
  }, [dirty]);
  useEffect(() => {
    if (!confirmLeave) return;
    const prompt =
      dialog.current?.querySelector<HTMLElement>("[data-leave-guard]");
    prompt?.scrollIntoView({ block: "nearest" });
    prompt?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [confirmLeave]);
  const changed = () => {
    if (!dialog.current) return;
    const modified = modifiedFields(dialog.current, baseline.current);
    setDirty(modified);
    if (timer.current) clearTimeout(timer.current);
    if (modified) {
      setDraftMessage("초안을 보관하고 있어요…");
      timer.current = setTimeout(() => {
        void store()
          .then(() =>
            setDraftMessage(
              "내 계정에 초안을 보관했습니다. 최종 문서 저장은 아래 저장 버튼으로 진행하세요.",
            ),
          )
          .catch(() =>
            setDraftMessage(
              "초안을 보관하지 못했습니다. 창을 닫기 전에 다시 보관해 주세요.",
            ),
          );
      }, 750);
    }
  };
  const recover = () => {
    if (!dialog.current || !draft) return;
    // Recovered text requires a fresh human confirmation.
    dialog.current
      .querySelectorAll<HTMLInputElement>('input[type="checkbox"]')
      .forEach((field) => {
        if (field.checked && !field.disabled) field.click();
      });
    fields(dialog.current).forEach((field, index) => {
      const value = draft.payload[`${index}:${field.name || field.id}`];
      if (!value || value.kind !== field.type) return;
      const prototype =
        field instanceof HTMLTextAreaElement
          ? HTMLTextAreaElement.prototype
          : field instanceof HTMLSelectElement
            ? HTMLSelectElement.prototype
            : HTMLInputElement.prototype;
      Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(
        field,
        value.value,
      );
      field.dispatchEvent(new Event("input", { bubbles: true }));
      field.dispatchEvent(new Event("change", { bubbles: true }));
    });
    setDraft(null);
    changed();
  };
  const finish = async (keep: boolean) => {
    try {
      if (timer.current) clearTimeout(timer.current);
      if (keep) await store();
      else
        await lastWrite.current
          .catch(() => {})
          .then(() => request(path, undefined, "DELETE"));
      setConfirmLeave(false);
      setDirty(false);
      const action = leave.current;
      leave.current = null;
      action?.();
    } catch {
      setDraftMessage(
        "초안 처리가 끝나지 않았습니다. 연결을 확인하고 다시 시도해 주세요.",
      );
    }
  };
  return (
    <dialog
      ref={dialog}
      className="editor-dialog"
      aria-label="지원 문서 직접 편집"
      onChangeCapture={changed}
      onInputCapture={changed}
      onCancel={(event) => {
        event.preventDefault();
        guard(onClose);
      }}
    >
      <div className="editor-heading">
        <div>
          <span className="eyebrow">WORKSPACE EDITOR</span>
          <h2>지원 문서 직접 편집</h2>
        </div>
        <button
          className="secondary"
          onClick={() => guard(onClose)}
          aria-label="편집창 닫기"
        >
          닫기 ×
        </button>
      </div>
      {draft && (
        <div className="draft-recovery" role="status">
          <p>
            보관한 초안이 있습니다 ·{" "}
            {new Date(draft.updated_at).toLocaleString("ko-KR")}
          </p>
          {(draft.stale_base ||
            (draft.base_artifact_id &&
              draft.base_artifact_id !== baseArtifactId)) && (
            <p className="muted">
              문서 버전이 바뀌었습니다. 복구한 내용을 현재 근거와 다시 대조해
              주세요.
            </p>
          )}
          <button onClick={recover}>초안 복구</button>
          <button
            className="secondary"
            onClick={() => {
              void request(path, undefined, "DELETE")
                .then(() => setDraft(null))
                .catch(() => setDraftMessage("초안을 지우지 못했습니다."));
            }}
          >
            보관 초안 지우기
          </button>
        </div>
      )}
      {draftMessage && (
        <p className="muted" role="status">
          {draftMessage}
        </p>
      )}
      {confirmLeave && (
        <div className="draft-recovery" role="alert" data-leave-guard>
          <h3>아직 문서로 저장하지 않은 내용이 있습니다.</h3>
          <p>초안을 계정에 보관하면 다음에 이 편집창에서 복구할 수 있습니다.</p>
          <button onClick={() => void finish(true)}>초안 보관하고 이동</button>
          <button className="secondary" onClick={() => setConfirmLeave(false)}>
            계속 편집
          </button>
          <button className="text-button" onClick={() => void finish(false)}>
            변경 내용 버리기
          </button>
        </div>
      )}
      <EditorSaveContext.Provider
        value={{
          beginSave: (form) => beginSave((field) => field.form === form),
          beginNames: (names) =>
            beginSave((field) => names.includes(field.name)),
        }}
      >
        {children}
      </EditorSaveContext.Provider>
    </dialog>
  );
});
