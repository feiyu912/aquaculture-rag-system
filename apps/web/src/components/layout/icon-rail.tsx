"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Waves } from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { APP_NAME, NAV_ITEMS } from "@/lib/navigation";
import { cn } from "@/lib/utils";

export function IconRail() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="主导航"
      className="z-30 hidden h-full w-[var(--rail-width)] shrink-0 flex-col items-center gap-1 border-r border-border bg-surface py-3 lg:flex"
    >
      <Link
        href="/chat"
        aria-label={APP_NAME}
        className="group mb-3 flex size-10 items-center justify-center rounded-xl bg-gradient-to-br from-primary-500 to-primary-800 text-white shadow-sm transition-transform duration-200 ease-soft hover:scale-[1.03]"
      >
        <Waves className="size-5" strokeWidth={2.1} />
      </Link>

      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return (
          <Tooltip key={item.href} delayDuration={200}>
            <TooltipTrigger asChild>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "relative flex size-11 items-center justify-center rounded-xl transition-colors duration-150 ease-soft",
                  active
                    ? "bg-primary-50 text-primary-700 dark:bg-primary-500/12 dark:text-primary-400"
                    : "text-subtle-foreground hover:bg-surface-muted hover:text-foreground",
                )}
              >
                {active && (
                  <span className="absolute -left-[8px] h-5 w-[3px] rounded-full bg-primary-600" />
                )}
                <Icon className="size-[19px]" strokeWidth={active ? 2.1 : 1.75} />
                <span className="sr-only">{item.label}</span>
              </Link>
            </TooltipTrigger>
            <TooltipContent side="right" className="flex flex-col gap-0.5">
              <span className="text-[12px] font-medium text-foreground">{item.label}</span>
              <span className="text-[11px] text-muted-foreground">{item.description}</span>
            </TooltipContent>
          </Tooltip>
        );
      })}
    </nav>
  );
}
