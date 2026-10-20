"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/lib/navigation";
import { cn } from "@/lib/utils";

/**
 * Bottom tab bar used below the `lg` breakpoint, where the vertical icon
 * rail would eat too much of a narrow viewport.
 */
export function MobileNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="主导航"
      className="fixed inset-x-0 bottom-0 z-40 flex h-14 items-stretch border-t border-border bg-surface/95 pb-[env(safe-area-inset-bottom)] backdrop-blur-md lg:hidden"
    >
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        const Icon = item.icon;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex flex-1 flex-col items-center justify-center gap-1 transition-colors duration-150",
              active ? "text-primary-700 dark:text-primary-400" : "text-subtle-foreground",
            )}
          >
            <Icon className="size-[19px]" strokeWidth={active ? 2.1 : 1.75} />
            <span className="text-[10.5px] font-medium leading-none">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
