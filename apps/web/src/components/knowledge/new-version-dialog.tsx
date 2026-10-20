"use client";

import * as React from "react";
import { CheckCircle2, FileUp, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { useDocumentMutations } from "@/hooks/use-documents";
import { documentsApi } from "@/lib/api/documents";
import type { DocumentOut } from "@/lib/api/types";

type Phase = "pick" | "uploading" | "processing" | "done" | "failed";

/**
 * Standalone "upload a new version" flow.
 *
 * The new version is only promoted to the active version after the worker
 * has parsed, chunked and indexed it; the old version is archived and can be
 * rolled back from the version history.
 */
export function NewVersionDialog({
  document,
  onClose,
}: {
  document: DocumentOut | null;
  onClose: () => void;
}) {
  const { addVersion } = useDocumentMutations();
  const [file, setFile] = React.useState<File | null>(null);
  const [phase, setPhase] = React.useState<Phase>("pick");
  const [progress, setProgress] = React.useState(0);
  const [stage, setStage] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const timerRef = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (!document) return;
    setFile(null);
    setPhase("pick");
    setProgress(0);
    setStage("");
    setError(null);
  }, [document]);

  React.useEffect(
    () => () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    },
    [],
  );

  const pollJob = React.useCallback(
    (jobId: string) => {
      const tick = async () => {
        try {
          const job = await documentsApi.job(jobId);
          setProgress(job.progress ?? 0);
          setStage(job.current_stage ?? "");
          if (job.status === "succeeded") {
            setPhase("done");
            toast.success("新版本已生效", {
              description: `「${document?.title ?? "文档"}」已切换到新版本`,
            });
            return;
          }
          if (job.status === "failed" || job.status === "cancelled") {
            setPhase("failed");
            setError(job.error_message ?? job.error_code ?? "入库任务失败");
            return;
          }
        } catch {
          /* keep polling */
        }
        timerRef.current = setTimeout(tick, 1200);
      };
      void tick();
    },
    [document],
  );

  const handleUpload = async () => {
    if (!file || !document) return;
    const form = new FormData();
    form.append("file", file);
    setPhase("uploading");
    setError(null);
    try {
      const result = await addVersion.mutateAsync({ documentId: document.id, form });
      setPhase("processing");
      setProgress(0);
      pollJob(result.job_id);
    } catch (err) {
      setPhase("failed");
      setError(err instanceof Error ? err.message : "上传失败");
    }
  };

  // All hooks must run before the early return, otherwise React sees a
  // different hook order on the next render.
  if (!document) return null;

  const busy = phase === "uploading" || phase === "processing";

  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>上传新版本</DialogTitle>
          <DialogDescription>
            为「{document.title}」追加一个修订版本。当前生效的是 v
            {document.current_version_no ?? "—"}，新版本在解析与向量化全部成功后才会切换。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {phase === "pick" && (
            <>
              <label
                htmlFor="new-version-file"
                className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border-2 border-dashed border-border-strong bg-surface-muted px-4 py-7 text-center transition-colors hover:border-primary-300 hover:bg-primary-soft"
              >
                <span className="flex size-10 items-center justify-center rounded-xl bg-primary-soft text-primary-soft-fg">
                  <FileUp className="size-5" />
                </span>
                <span className="text-[13px] font-medium text-foreground">
                  {file ? file.name : "选择新的 PDF 文件"}
                </span>
                <span className="text-[11.5px] text-muted-foreground">
                  {file ? `${(file.size / 1024).toFixed(0)} KB` : "最大 100 MB，仅支持 PDF"}
                </span>
                <Input
                  id="new-version-file"
                  type="file"
                  accept="application/pdf,.pdf"
                  className="sr-only"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                />
              </label>

              <p className="rounded-lg bg-surface-muted px-3 py-2.5 text-[11.5px] leading-5 text-muted-foreground">
                新版本入库成功后，旧版本会转为归档并可在「版本历史」中随时回滚；上传失败不会影响当前生效版本。
              </p>
            </>
          )}

          {(phase === "uploading" || phase === "processing") && (
            <div className="rounded-xl border border-border bg-surface-muted px-4 py-4">
              <div className="flex items-center gap-2">
                <Loader2 className="size-4 animate-spin text-primary-600" />
                <span className="text-[13px] font-medium text-foreground">
                  {phase === "uploading" ? "正在上传…" : `正在入库：${stage || "排队中"}`}
                </span>
              </div>
              <Progress value={progress} className="mt-3" />
              <p className="mt-2 text-[11.5px] text-muted-foreground">
                {file?.name} · {progress}%
              </p>
            </div>
          )}

          {phase === "done" && (
            <div className="flex items-start gap-2.5 rounded-xl border border-success/25 bg-success-soft px-4 py-3.5">
              <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
              <div>
                <p className="text-[13px] font-semibold text-foreground">新版本已生效</p>
                <p className="mt-0.5 text-[12.5px] leading-5 text-muted-foreground">
                  旧版本已归档，可在「版本历史」中回滚。
                </p>
              </div>
            </div>
          )}

          {phase === "failed" && (
            <div className="rounded-xl border border-danger/25 bg-danger-soft px-4 py-3.5">
              <p className="text-[13px] font-semibold text-foreground">新版本入库失败</p>
              <p className="mt-0.5 text-[12.5px] leading-5 text-muted-foreground">{error}</p>
              <p className="mt-1.5 text-[11.5px] text-muted-foreground">
                当前生效版本未受影响，可以重新选择文件再试。
              </p>
            </div>
          )}
        </div>

        <DialogFooter>
          {phase === "done" ? (
            <Button onClick={onClose}>完成</Button>
          ) : (
            <>
              <Button variant="ghost" onClick={onClose} disabled={busy}>
                取消
              </Button>
              {phase === "failed" ? (
                <Button variant="outline" onClick={() => setPhase("pick")}>
                  重新选择
                </Button>
              ) : (
                <Button onClick={handleUpload} disabled={!file || busy}>
                  <Upload className="size-4" />
                  上传并入库
                </Button>
              )}
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
