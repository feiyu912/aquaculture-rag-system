import { Suspense } from "react";

import { DebugClient } from "@/components/debug/debug-client";

export default function DebugPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center bg-background">
          <span className="text-[13px] text-muted-foreground">正在加载调试面板…</span>
        </div>
      }
    >
      <DebugClient />
    </Suspense>
  );
}
