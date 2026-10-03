"use client";

import { useEffect, useRef, useState } from "react";
import type {
  PDFDocumentProxy,
  PDFDocumentLoadingTask,
  RenderTask,
} from "pdfjs-dist";

// Render the actual owned PDF, without relying on a browser PDF plugin.
export function PdfPages({ url }: { url: string }) {
  const [document, setDocument] = useState<PDFDocumentProxy | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [width, setWidth] = useState(300);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const holder = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const element = holder.current;
    if (!element) return;
    const observer = new ResizeObserver(([entry]) =>
      setWidth(Math.max(160, Math.floor(entry.contentRect.width))),
    );
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let disposed = false;
    let task: PDFDocumentLoadingTask | undefined;
    setDocument(null);
    setError("");
    setLoading(true);
    setPageNumber(1);
    void (async () => {
      try {
        const pdfjs = await import("pdfjs-dist");
        pdfjs.GlobalWorkerOptions.workerSrc = new URL(
          "pdfjs-dist/build/pdf.worker.min.mjs",
          import.meta.url,
        ).toString();
        if (disposed) return;
        task = pdfjs.getDocument({
          url,
          useWorkerFetch: false,
        });
        const result = await task.promise;
        if (!disposed) setDocument(result);
      } catch {
        if (!disposed) {
          setLoading(false);
          setError(
            "PDF 페이지를 표시하지 못했습니다. 파일을 내려받아 확인해 주세요.",
          );
        }
      }
    })();
    return () => {
      disposed = true;
      if (task) void task.destroy().catch(() => {});
    };
  }, [url]);

  useEffect(() => {
    if (!document || !canvas.current) return;
    let disposed = false;
    let renderTask: RenderTask | undefined;
    const element = canvas.current;
    setLoading(true);
    setError("");
    void (async () => {
      try {
        const page = await document.getPage(pageNumber);
        if (disposed) return;
        const natural = page.getViewport({ scale: 1 });
        const ratio = Math.min(window.devicePixelRatio || 1, 2);
        const viewport = page.getViewport({
          scale: (width / natural.width) * ratio,
        });
        element.width = Math.ceil(viewport.width);
        element.height = Math.ceil(viewport.height);
        renderTask = page.render({ canvas: element, viewport });
        await renderTask.promise;
        if (!disposed) setLoading(false);
      } catch {
        if (!disposed) {
          setLoading(false);
          setError(
            "페이지를 표시하지 못했습니다. 다시 열거나 파일을 내려받아 확인해 주세요.",
          );
        }
      }
    })();
    return () => {
      disposed = true;
      renderTask?.cancel();
    };
  }, [document, pageNumber, width]);

  return (
    <div className="pdf-page-reader" ref={holder}>
      {document && (
        <div className="pdf-page-controls">
          <button
            className="text-button"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber(pageNumber - 1)}
          >
            이전 페이지
          </button>
          <span>
            {pageNumber} / {document.numPages}페이지
          </span>
          <button
            className="text-button"
            disabled={pageNumber >= document.numPages}
            onClick={() => setPageNumber(pageNumber + 1)}
          >
            다음 페이지
          </button>
        </div>
      )}
      {loading && <p role="status">실제 PDF 페이지를 그리고 있어요…</p>}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      <canvas
        ref={canvas}
        role="img"
        aria-label={`이력서 실제 PDF ${pageNumber}페이지`}
        hidden={Boolean(error) || !document}
      />
    </div>
  );
}
