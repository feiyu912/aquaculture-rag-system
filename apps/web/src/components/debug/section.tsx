"use client";

import * as React from "react";
import { ChevronDown, Code2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function RawTrace({ value }: { value: unknown }) {
  const [open, setOpen] = React.useState(false);
  const json = React.useMemo(() => JSON.stringify(value, null, 2), [value]);

  return (
    <div className="instrument-panel overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        className="flex w-full items-center gap-2 px-4 py-3 text-left transition-colors hover:bg-instrument-raised"
      >
        <Code2 className="size-4 text-instrument-muted" />
        <span className="text-[13px] font-semibold text-instrument-foreground">
          原始 Trace
        </span>
        <span className="text-[11.5px] text-instrument-muted">
          完整的 request_id 记录（rankings / evidence / gate / timings）
        </span>
        <ChevronDown
          className={cn(
            "ml-auto size-4 text-instrument-muted transition-transform duration-200",
            open && "rotate-180",
          )}
        />
      </button>
      {open && (
        <pre className="max-h-[420px] overflow-auto border-t border-instrument-border bg-instrument-inset px-4 py-3 font-mono text-[11.5px] leading-[1.7] text-instrument-foreground">
          {json}
        </pre>
      )}
    </div>
  );
}

export function Section({
  title,
  hint,
  action,
  children,
  className,
  tone = "light",
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  tone?: "light" | "instrument";
}) {
  return (
    <section
      className={cn(
        tone === "instrument" ? "instrument-panel" : "surface-card",
        "overflow-hidden",
        className,
      )}
    >
      <header
        className={cn(
          "flex items-center gap-2 border-b px-4 py-3",
          tone === "instrument"
            ? "border-instrument-border"
            : "border-border",
        )}
      >
        <h2
          className={cn(
            "text-[13px] font-semibold",
            tone === "instrument" ? "text-instrument-foreground" : "text-foreground",
          )}
        >
          {title}
        </h2>
        {hint && (
          <span
            className={cn(
              "text-[11.5px]",
              tone === "instrument" ? "text-instrument-muted" : "text-subtle-foreground",
            )}
          >
            {hint}
          </span>
        )}
        {action && <div className="ml-auto">{action}</div>}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}
