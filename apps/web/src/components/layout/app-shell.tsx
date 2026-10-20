"use client";

import * as React from "react";

import { IconRail } from "@/components/layout/icon-rail";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ShellContext, type ShellContextValue } from "@/components/layout/shell-context";
import { TopBar } from "@/components/layout/top-bar";
import { cn } from "@/lib/utils";

export function AppShell({
  children,
  context,
  contextLabel = "侧栏",
  className,
}: {
  children: React.ReactNode;
  context?: React.ReactNode;
  contextLabel?: string;
  className?: string;
}) {
  const [mobileContextOpen, setMobileContextOpen] = React.useState(false);
  const [contextCollapsed, setContextCollapsed] = React.useState(false);
  const [label, setLabel] = React.useState(contextLabel);

  React.useEffect(() => {
    setLabel(contextLabel);
  }, [contextLabel]);

  const hasContext = Boolean(context);

  const value = React.useMemo(
    () => ({
      contextLabel: label,
      setContextLabel: setLabel,
      hasContext,
      contextCollapsed,
      setContextCollapsed,
      mobileContextOpen,
      setMobileContextOpen,
    }),
    [label, hasContext, contextCollapsed, mobileContextOpen],
  );

  return (
    <ShellContext.Provider value={value}>
      <div className={cn("flex h-dvh flex-col overflow-hidden bg-background", className)}>
        <TopBar />

        <div className="flex min-h-0 flex-1">
          <IconRail />

          {context ? (
            <aside
              className={cn(
                "hidden shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200 ease-soft lg:flex",
                contextCollapsed ? "w-0 overflow-hidden border-r-0" : "w-[var(--context-width)]",
              )}
            >
              {context}
            </aside>
          ) : null}

          <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden pb-14 lg:pb-0">
            {children}
          </main>
        </div>

        <MobileNav />

        {/* Mobile context drawer */}
        {context ? (
          <div
            className={cn(
              "fixed inset-0 z-50 lg:hidden",
              mobileContextOpen ? "pointer-events-auto" : "pointer-events-none",
            )}
            aria-hidden={!mobileContextOpen}
          >
            <div
              className={cn(
                "absolute inset-0 bg-foreground/30 transition-opacity duration-200",
                mobileContextOpen ? "opacity-100" : "opacity-0",
              )}
              onClick={() => setMobileContextOpen(false)}
            />
            <div
              className={cn(
                "absolute inset-y-0 left-0 flex w-[min(86vw,320px)] flex-col border-r border-border bg-surface shadow-xl transition-transform duration-250 ease-soft",
                mobileContextOpen ? "translate-x-0" : "-translate-x-full",
              )}
            >
              <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
                <span className="text-[13px] font-semibold text-foreground">{label}</span>
                <button
                  type="button"
                  onClick={() => setMobileContextOpen(false)}
                  aria-label="关闭"
                  className="rounded-md p-1.5 text-subtle-foreground transition-colors hover:bg-surface-muted hover:text-foreground"
                >
                  <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6 6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <div className="flex min-h-0 flex-1 flex-col">{context}</div>
            </div>
          </div>
        ) : null}
      </div>
    </ShellContext.Provider>
  );
}
