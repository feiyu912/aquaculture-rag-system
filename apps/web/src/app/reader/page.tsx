"use client";

import { Construction } from "lucide-react";

import { AppShell } from "@/components/layout/app-shell";

export default function ReaderPage() {
  return (
    <AppShell contextLabel="页面">
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-sm text-center">
          <Construction className="mx-auto size-6 text-subtle-foreground" />
          <h2 className="mt-3 text-[15px] font-semibold text-foreground">文献阅读器正在接入</h2>
          <p className="mt-1.5 text-[13px] leading-6 text-muted-foreground">
            该模块将在下一阶段接入 PDF.js 渲染与引用 bbox 高亮定位。
          </p>
        </div>
      </div>
    </AppShell>
  );
}
