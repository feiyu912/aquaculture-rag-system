"use client";

import { Toaster as SonnerToaster } from "sonner";
import { useTheme } from "@/components/providers/theme-provider";

export function Toaster() {
  const { resolvedTheme } = useTheme();

  return (
    <SonnerToaster
      theme={resolvedTheme}
      position="bottom-right"
      offset={16}
      toastOptions={{
        classNames: {
          toast:
            "group rounded-xl border border-border bg-surface-overlay text-foreground shadow-lg text-[13px]",
          description: "text-muted-foreground",
          actionButton: "bg-primary-700 text-white",
          cancelButton: "bg-surface-muted text-muted-foreground",
        },
      }}
    />
  );
}
