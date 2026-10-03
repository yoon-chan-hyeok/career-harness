"use client";
import { useEffect, useRef, useState } from "react";
import type { Request } from "./api-client";
import { PdfPages } from "./pdf-pages";

type Upload = {
  id: string;
  filename: string;
  text: string;
  pages: { number: number; text: string }[];
  warnings: string[];
  status: string;
};
export function SourceUpload({
  request,
  refresh,
}: {
  request: Request;
  refresh: () => Promise<void>;
}) {
  const [upload, setUpload] = useState<Upload | null>(null);
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState("EVIDENCE");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const read = async (file?: File) => {
    if (!file) return;
    setMessage("");
    setUpload(null);
    setConfirmed(false);
    if (file.size > 2_000_000) {
      setMessage(
        "2MB 이하의 파일을 올려 주세요. 큰 자료는 나눠서 올릴 수 있습니다.",
      );
      return;
    }
    setBusy(true);
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let binary = "";
      for (let start = 0; start < bytes.length; start += 8192)
        binary += String.fromCharCode(...bytes.subarray(start, start + 8192));
      const result: Upload = await request("/sources/upload", {
        filename: file.name,
        content_base64: btoa(binary),
      });
      setUpload(result);
      setTitle(file.name.replace(/\.[^.]+$/, ""));
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "파일을 읽지 못했습니다.",
      );
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const save = async () => {
    if (!upload) return;
    setBusy(true);
    setMessage("");
    try {
      await request(`/sources/uploads/${upload.id}/confirm`, {
        confirmed,
        title,
        kind,
      });
      await refresh();
      setUpload(null);
      setConfirmed(false);
      setMessage(
        "확인한 자료를 저장했습니다. 경험의 수행 범위와 수치는 원자료를 보며 별도로 확인하세요.",
      );
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "자료를 저장하지 못했습니다.",
      );
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="source-upload">
      <h3>자료 파일 가져오기</h3>
      <p className="muted">
        PDF·DOCX·텍스트 자료를 읽고 내용을 먼저 보여 드립니다. 확인하기 전에는
        사실 근거에 반영하지 않습니다.
      </p>
      <label>
        자료 파일 (최대 2MB)
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.txt,.md"
          disabled={busy}
          onChange={(event) => void read(event.target.files?.[0])}
        />
      </label>
      {busy && <p role="status">자료를 처리하고 있어요…</p>}
      {upload && (
        <div className="upload-preview">
          <h4>{upload.filename}</h4>
          {upload.warnings?.map((warning, index) => (
            <p className="note" key={index}>
              {warning}
            </p>
          ))}
          <details open>
            <summary>읽어 낸 내용 확인</summary>
            <pre>{upload.text}</pre>
          </details>
          {upload.pages?.length > 1 && (
            <details>
              <summary>페이지별 확인</summary>
              {upload.pages.map((page) => (
                <details key={page.number}>
                  <summary>{page.number}페이지</summary>
                  <pre>{page.text}</pre>
                </details>
              ))}
            </details>
          )}
          <label>
            자료 이름
            <input
              value={title}
              onChange={(event) => {
                setTitle(event.target.value);
                setConfirmed(false);
              }}
            />
          </label>
          <label>
            저장 용도
            <select
              value={kind}
              onChange={(event) => {
                setKind(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="EVIDENCE">경험 원자료 · 사실 확인용</option>
              <option value="EXPRESSION">과거 글 · 표현 참고용</option>
            </select>
          </label>
          <label className="check">
            <input
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            원자료와 대조해 추출 내용을 확인했습니다.
          </label>
          <button
            disabled={
              busy || !confirmed || !title.trim() || !upload.text.trim()
            }
            onClick={() => void save()}
          >
            확인한 자료 저장
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => setUpload(null)}
          >
            이번 자료 취소
          </button>
        </div>
      )}
      {message && (
        <p role="status" className="note">
          {message}
        </p>
      )}
    </section>
  );
}

export function ResumeFiles({
  workspaceId,
  artifactId,
  send,
}: {
  workspaceId: string;
  artifactId: string;
  send: (path: string) => Promise<Response>;
}) {
  const [preview, setPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pageInfo, setPageInfo] = useState<{
    pages: number | null;
    budget: string;
    overflow: boolean;
  } | null>(null);
  const [wordNotice, setWordNotice] = useState(false);
  const [largePreview, setLargePreview] = useState(false);
  const previewDialog = useRef<HTMLDialogElement>(null);
  const version = useRef(0);
  useEffect(() => {
    if (largePreview) previewDialog.current?.showModal();
    else previewDialog.current?.close();
  }, [largePreview]);
  useEffect(() => {
    version.current += 1;
    setPreview("");
    setPageInfo(null);
    setWordNotice(false);
    setLargePreview(false);
    setBusy(false);
    setError("");
    return () => {
      version.current += 1;
    };
  }, [artifactId]);
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );
  const load = async (format: "pdf" | "docx", show = false) => {
    const currentVersion = version.current;
    setBusy(true);
    setError("");
    try {
      const response = await send(
        `/applications/${workspaceId}/resume/download?format=${format}&artifact_id=${encodeURIComponent(artifactId)}`,
      );
      const blob = await response.blob();
      if (version.current !== currentVersion) return;
      if (format === "pdf") {
        const pageCount = Number(response.headers.get("X-Page-Count"));
        setPageInfo({
          pages:
            Number.isInteger(pageCount) && pageCount > 0 ? pageCount : null,
          budget: response.headers.get("X-Page-Budget") || "미확인",
          overflow: response.headers.get("X-Page-Overflow") === "true",
        });
      } else setWordNotice(true);
      const url = URL.createObjectURL(blob);
      if (show) setPreview(url);
      else {
        const link = document.createElement("a");
        link.href = url;
        link.download = `resume.${format}`;
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }
    } catch (error) {
      if (version.current !== currentVersion) return;
      setError(
        error instanceof Error
          ? error.message
          : "이력서 파일을 만들지 못했습니다.",
      );
    } finally {
      if (version.current === currentVersion) setBusy(false);
    }
  };
  return (
    <div className="resume-files">
      <h4>제출용 파일</h4>
      <div className="row">
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void load("pdf", true)}
        >
          실제 PDF 미리보기
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void load("pdf")}
        >
          PDF 내려받기
        </button>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void load("docx")}
        >
          DOCX 내려받기
        </button>
      </div>
      {pageInfo && (
        <p role="status" className="muted">
          실제 PDF{" "}
          {pageInfo.pages === null
            ? "페이지 수 미확인"
            : `${pageInfo.pages}페이지`}{" "}
          ·
          {pageInfo.budget === "MASTER"
            ? " 마스터 분량"
            : ` 목표 ${pageInfo.budget}페이지`}
        </p>
      )}
      {pageInfo?.overflow && (
        <p role="alert" className="note">
          본문을 자르지 않아 목표 분량을 초과했습니다. 내용을 줄인 뒤 다시
          출력해 주세요.
        </p>
      )}
      {wordNotice && (
        <p className="muted">
          Word의 페이지 배치는 사용하는 프로그램과 글꼴에 따라 달라집니다. 제출
          전에 파일을 열어 확인해 주세요.
        </p>
      )}
      {preview && (
        <div className="pdf-preview">
          <PdfPages url={preview} />
          <p className="muted">
            실제 PDF 파일입니다. 페이지 수·잘림·날짜·링크를 확인한 뒤 파일
            검토를 기록하세요.
          </p>
          <button className="text-button" onClick={() => setLargePreview(true)}>
            페이지 크게 보기
          </button>
          <dialog
            ref={previewDialog}
            className="pdf-document-dialog"
            onCancel={() => setLargePreview(false)}
          >
            <div className="pdf-document-heading">
              <h3>이력서 실제 PDF</h3>
              <button
                className="secondary"
                autoFocus
                onClick={() => setLargePreview(false)}
              >
                닫기
              </button>
            </div>
            {largePreview && <PdfPages url={preview} />}
          </dialog>
          <button
            className="text-button"
            onClick={() => {
              setLargePreview(false);
              setPreview("");
            }}
          >
            미리보기 닫기
          </button>
        </div>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
    </div>
  );
}
