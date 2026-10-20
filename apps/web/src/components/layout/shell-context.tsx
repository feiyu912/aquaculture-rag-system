"use client";

import * as React from "react";

export interface ShellContextValue {
  contextLabel: string;
  setContextLabel: (label: string) => void;
  hasContext: boolean;
  contextCollapsed: boolean;
  setContextCollapsed: (collapsed: boolean) => void;
  mobileContextOpen: boolean;
  setMobileContextOpen: (open: boolean) => void;
}

export const ShellContext = React.createContext<ShellContextValue | null>(null);

/**
 * A safe fallback keeps the tree renderable when the provider is missing
 * (for example during a Fast Refresh module swap, where the provider and the
 * consumer can briefly end up bound to different context objects).
 */
const FALLBACK: ShellContextValue = {
  contextLabel: "侧栏",
  setContextLabel: () => undefined,
  hasContext: false,
  contextCollapsed: false,
  setContextCollapsed: () => undefined,
  mobileContextOpen: false,
  setMobileContextOpen: () => undefined,
};

export function useShell(): ShellContextValue {
  return React.useContext(ShellContext) ?? FALLBACK;
}
