"use client";

import * as React from "react";
import { FileUp, Loader2, UploadCloud, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";

export interface UploadItem {
  id: string;
  fileName: string;
  fileSize: number;
  status: "queued" | "uploading" | "processing" | "succeeded" | "failed";
  progress: number;
  stage?: string;
  error?: string;
  documentId?: string;
  jobId?: string;
}

export function UploadDropzone({
  onFiles,
  disabled,
}: {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}) {
  const [dragging, setDragging] = React.useState(false);
  const inputRef = React.useRef<HTMLInputElement>(null);

  const handleDrop = (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    const files = Array.from(event.dataTransfer.files).filter(
      (file) => file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf"),
    );
    if (files.length) onFiles(files);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cn(
        "relative flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed px-6 py-9 text-center transition-colors duration-200 ease-soft",
        dragging
          ? "border-primary-btn bg-primary-soft"
          : "border-border-strong bg-surface hover:border-primary-300 hover:bg-surface-muted",
      )}
    >
      <span
        className={cn(
          "flex size-11 items-center justify-center rounded-xl transition-colors duration-200",
          dragging ? "bg-primary-btn text-primary-fg" : "bg-primary-soft text-primary-soft-fg",
        )}
      >
        <UploadCloud className="size-5" />
      </span>

      <div>
        <p className="text-[13.5px] font-semibold text-foreground">
          拖拽 PDF 到此处上传
        </p>
        <p className="mt-1 text-[12px] text-muted-foreground">
          单个文件最大 100 MB，上传后由 ARQ worker 解析、切分并向量化
        </p>
      </div>

      <Button
        variant="outline"
        size="sm"
        onClick={() => inputRef.current?.click()}
        disabled={disabled}
      >
        <FileUp className="size-4" />
        选择文件
      </Button>

      <input
        ref={inputRef}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        className="hidden"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length) onFiles(files);
          event.target.value = "";
        }}
      />
    </div>
  );
}

export function UploadQueueItem({ item }: { item: UploadItem }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-border bg-surface px-3.5 py-3">
      <span
        className={cn(
          "mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg",
          item.status === "failed"
            ? "bg-danger-soft text-danger"
            : item.status === "succeeded"
              ? "bg-success-soft text-success"
              : "bg-primary-soft text-primary-soft-fg",
        )}
      >
        {item.status === "uploading" || item.status === "processing" ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <FileUp className="size-4" />
        )}
      </span>

      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
            {item.fileName}
          </p>
          {item.status === "succeeded" && (
            <span className="text-[11.5px] font-medium text-success">已入库</span>
          )}
          {item.status === "failed" && (
            <span className="text-[11.5px] font-medium text-danger">失败</span>
          )}
        </div>

        {item.status === "uploading" || item.status === "processing" ? (
          <div className="mt-2">
            <Progress value={item.progress} />
            <p className="mt-1.5 text-[11.5px] text-muted-foreground">
              {item.stage ?? "处理中…"} {item.progress > 0 ? `${item.progress}%` : ""}
            </p>
          </div>
        ) : item.error ? (
          <p className="mt-1 text-[11.5px] leading-5 text-danger">{item.error}</p>
        ) : (
          <p className="mt-1 text-[11.5px] text-muted-foreground">
            {item.status === "queued" ? "等待上传" : "解析完成，版本已激活"}
          </p>
        )}
      </div>
    </div>
  );
}

export function UploadQueue({
  items,
  onDismiss,
}: {
  items: UploadItem[];
  onDismiss: (id: string) => void;
}) {
  if (items.length === 0) return null;

  return (
    <div className="flex flex-col gap-2">
      {items.map((item) => (
        <div key={item.id} className="relative">
          <UploadQueueItem item={item} />
          {item.status === "succeeded" || item.status === "failed" ? (
            <button
              type="button"
              onClick={() => onDismiss(item.id)}
              aria-label="移除记录"
              className="absolute right-2 top-2 rounded-md p-1 text-subtle-foreground transition-colors hover:bg-surface-muted hover:text-foreground"
            >
              <X className="size-3.5" />
            </button>
          ) : null}
        </div>
      ))}
    </div>
  );
}
