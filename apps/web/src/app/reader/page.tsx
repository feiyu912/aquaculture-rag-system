import { Suspense } from "react";

import { ReaderClient } from "@/components/reader/reader-client";

export default function ReaderPage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center bg-background">
          <span className="text-[13px] text-muted-foreground">正在加载阅读器…</span>
        </div>
      }
    >
      <ReaderClient />
    </Suspense>
  );
}
