"use client";

import { Construction } from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";

export default function DebugPage() {
  return (
    <AppShell contextLabel="链路">
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <Construction className="mx-auto size-6 text-subtle-foreground" />
          <h2 className="mt-3 text-[15px] font-semibold text-foreground">检索调试面板正在接入</h2>
          <p className="mt-1.5 text-[13px] leading-6 text-muted-foreground">
            该模块将在下一阶段接入真实 Trace 接口，展示 Query IR、融合与重排链路。
          </p>
        </div>
      </div>
    </AppShell>
  );
}
