"use client";

import * as React from "react";

import { API_BASE_URL } from "@/lib/api/client";

type PdfJsModule = typeof import("pdfjs-dist");

let pdfjsPromise: Promise<PdfJsModule> | null = null;

/**
 * Load pdf.js in the browser and point it at the static worker copy.
 *
 * The worker file is produced by `scripts/copy-pdf-worker.mjs` (run on
 * `postinstall`) so the reader also works without network access.
 */
export function loadPdfJs(): Promise<PdfJsModule> {
  if (!pdfjsPromise) {
    pdfjsPromise = import("pdfjs-dist").then(async (pdfjs) => {
      pdfjs.GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs";
      return pdfjs;
    });
  }
  return pdfjsPromise;
}

export interface LoadedDocument {
  /** The pdf.js document proxy. */
  doc: import("pdfjs-dist").PDFDocumentProxy;
  /** File name shown in the toolbar. */
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
    // Keep the raw bytes so pdf.js can fetch ranges if the browser allows it.
    disableAutoFetch: false,
    disableStream: false,
  }).promise;

  return { doc, name: url.split("/").pop() ?? "document.pdf", numPages: doc.numPages };
}
