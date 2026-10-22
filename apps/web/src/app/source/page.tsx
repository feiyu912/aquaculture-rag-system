import { Suspense } from "react";

import { AppShell } from "@/components/layout/app-shell";
import { SourceView } from "@/components/source/source-view";

export default function SourcePage() {
  return (
    <AppShell>
      <Suspense
        fallback={
          <div className="flex h-full items-center justify-center bg-background">
            <span className="text-[13px] text-muted-foreground">正在加载来源…</span>
          </div>
        }
      >
        <SourceView />
      </Suspense>
    </AppShell>
  );
}
