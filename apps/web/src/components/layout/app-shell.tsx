"use client";

import * as React from "react";

import { IconRail } from "@/components/layout/icon-rail";
import { MobileNav } from "@/components/layout/mobile-nav";
import { ShellContext, type ShellContextValue } from "@/components/layout/shell-context";
import { TopBar } from "@/components/layout/top-bar";
import { useContextWidth, useResizeHandle } from "@/hooks/use-context-width";
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

  const { width: contextWidth, setWidth: setContextWidth, reset: resetContextWidth } =
    useContextWidth();
  const { dragging, panelRef, handleProps } = useResizeHandle({
    onResize: setContextWidth,
    onReset: resetContextWidth,
    currentWidth: contextWidth,
  });

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
              style={
                contextCollapsed ? undefined : { width: contextWidth, minWidth: contextWidth }
              }
              ref={panelRef as React.RefObject<HTMLElement>}
            >
              {context}
            </aside>
          ) : null}

          {context && !contextCollapsed && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="调整侧栏宽度"
              tabIndex={0}
              title="拖动调整宽度，双击恢复默认"
              className={cn(
                "group relative z-20 hidden w-1 shrink-0 cursor-col-resize bg-border transition-colors lg:block",
                dragging ? "bg-primary-500" : "hover:bg-primary-400",
              )}
              {...handleProps}
            >
              <span
                className={cn(
                  "absolute left-1/2 top-1/2 h-10 w-[3px] -translate-x-1/2 -translate-y-1/2 rounded-full transition-colors",
                  dragging ? "bg-primary-500" : "bg-border-strong group-hover:bg-primary-400",
                )}
              />
            </div>
          )}

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
              role="dialog"
              aria-label={label}
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
