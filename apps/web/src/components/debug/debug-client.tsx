"use client";

import * as React from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "@/components/layout/app-shell";
import { DebugWorkspace } from "@/components/debug/debug-workspace";

export function DebugClient() {
  const searchParams = useSearchParams();

  return (
    <AppShell contextLabel="执行阶段">
      <DebugWorkspace initialRequestId={searchParams.get("request_id") ?? ""} />
    </AppShell>
  );
}
