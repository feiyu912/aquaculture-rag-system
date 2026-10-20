"use client";

import { API_BASE_URL } from "@/lib/api/client";

/**
 * The subset of the pdf.js public API the reader relies on.
 */
export interface PdfJsModule {
  getDocument: (options: {
    data: Uint8Array;
    cMapUrl?: string;
    cMapPacked?: boolean;
    standardFontDataUrl?: string;
  }) => { promise: Promise<PdfDocumentProxy> };
  GlobalWorkerOptions: { workerSrc: string };
  version: string;
  build: string;
}

export interface PdfViewport {
  width: number;
  height: number;
  scale: number;
  rotation: number;
  viewBox: number[];
  transform: number[];
  convertToViewportPoint: (x: number, y: number) => number[];
}

export interface PdfPageProxy {
  getViewport: (options: { scale: number; rotation?: number }) => PdfViewport;
  render: (options: {
    canvas: HTMLCanvasElement;
    canvasContext: CanvasRenderingContext2D;
    viewport: PdfViewport;
    transform?: number[];
  }) => { promise: Promise<void> };
  cleanup: () => void;
}

export interface PdfDocumentProxy {
  numPages: number;
  getPage: (pageNumber: number) => Promise<PdfPageProxy>;
  destroy: () => Promise<void>;
}

let pdfjsPromise: Promise<PdfJsModule> | null = null;

function injectModule(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(
      `script[data-pdf-src="${src}"]`,
    );
    if (existing) {
      if (existing.dataset.loaded === "true") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener("error", () => reject(new Error(`加载 ${src} 失败`)), {
        once: true,
      });
      return;
    }

    const script = document.createElement("script");
    script.type = "module";
    script.src = src;
    script.dataset.pdfSrc = src;
    script.addEventListener(
      "load",
      () => {
        script.dataset.loaded = "true";
        resolve();
      },
      { once: true },
    );
    script.addEventListener(
      "error",
      () => reject(new Error(`加载 ${src} 失败`)),
      { once: true },
    );
    document.head.appendChild(script);
  });
}

/**
 * Load pdf.js in the browser.
 *
 * The library is served from `public/` (see `scripts/copy-pdf-worker.mjs`) and
 * injected as an ES module so the bundler never re-processes pdf.js' own
 * webpack runtime.
 */
export function loadPdfJs(): Promise<PdfJsModule> {
  if (!pdfjsPromise) {
    pdfjsPromise = injectModule("/pdf.min.mjs").then(() => {
      const pdfjs = (window as unknown as { pdfjsLib?: PdfJsModule }).pdfjsLib;
      if (!pdfjs) {
        throw new Error("pdf.js 未能正确加载（pdfjsLib 未定义）");
      }
      pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
      return pdfjs;
    });
  }
  return pdfjsPromise;
}

export interface LoadedDocument {
  doc: PdfDocumentProxy;
  name: string;
  numPages: number;
}

export async function fetchPdf(
  documentId: string,
  versionId?: string | null,
): Promise<LoadedDocument> {
  const pdfjs = await loadPdfJs();
  const params = versionId ? `?version_id=${encodeURIComponent(versionId)}` : "";
  const url = `${API_BASE_URL}/api/documents/${documentId}/file${params}`;

  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`PDF 加载失败（HTTP ${response.status}）`);
  }

  const data = await response.arrayBuffer();
  const doc = await pdfjs.getDocument({
    data: new Uint8Array(data),
    // Required for CJK encodings; without them pdf.js renders blank pages.
    cMapUrl: "/cmaps/",
    cMapPacked: true,
    standardFontDataUrl: "/standard_fonts/",
  }).promise;

  return { doc, name: url.split("/").pop() ?? "document.pdf", numPages: doc.numPages };
}
