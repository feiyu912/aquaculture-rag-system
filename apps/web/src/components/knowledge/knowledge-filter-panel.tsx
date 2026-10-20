"use client";

import * as React from "react";
import { Filter, RotateCcw, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import { cn } from "@/lib/utils";

export interface KnowledgeFilters {
  query: string;
  category: string | null;
  species: string | null;
  status: "all" | "active" | "inactive";
}

export const EMPTY_FILTERS: KnowledgeFilters = {
  query: "",
  category: null,
  species: null,
  status: "all",
};

export function FilterGroup({
  title,
  options,
  value,
  onChange,
  counts,
}: {
  title: string;
  options: string[];
  value: string | null;
  onChange: (value: string | null) => void;
  counts?: Record<string, number>;
}) {
  if (options.length === 0) return null;

  return (
    <div>
      <p className="eyebrow mb-2">{title}</p>
      <div className="space-y-0.5">
        <button
          type="button"
          onClick={() => onChange(null)}
          className={cn(
            "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors duration-150",
            value === null
              ? "bg-primary-soft font-medium text-primary-soft-fg"
              : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
          )}
        >
          <span>全部</span>
          {counts ? (
            <span className="text-[11px] tabular-nums text-subtle-foreground">
              {Object.values(counts).reduce((sum, value) => sum + value, 0)}
            </span>
          ) : null}
        </button>
        {options.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(value === option ? null : option)}
            className={cn(
              "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors duration-150",
              value === option
                ? "bg-primary-soft font-medium text-primary-soft-fg"
                : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
            )}
          >
            <span className="truncate">{option}</span>
            {counts?.[option] !== undefined && (
              <span className="shrink-0 text-[11px] tabular-nums text-subtle-foreground">
                {counts[option]}
              </span>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

export function KnowledgeFilterPanel({
  filters,
  onChange,
  categories,
  speciesOptions,
}: {
  filters: KnowledgeFilters;
  onChange: (filters: KnowledgeFilters) => void;
  categories: string[];
  speciesOptions: string[];
}) {
  const dirty =
    filters.query !== "" ||
    filters.category !== null ||
    filters.species !== null ||
    filters.status !== "all";

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 px-3 pb-3 pt-3.5">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
            <Input
              value={filters.query}
              onChange={(event) => onChange({ ...filters, query: event.target.value })}
              placeholder="搜索文档标题"
              className="h-8 pl-8 text-[12.5px]"
              aria-label="搜索文档"
            />
          </div>
          {dirty && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="重置筛选"
              onClick={() => onChange(EMPTY_FILTERS)}
            >
              <RotateCcw className="size-3.5" />
            </Button>
          )}
        </div>
      </div>

      <Separator />

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 py-4">
        <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground">
          <Filter className="size-3.5" />
          筛选
        </div>

        <FilterGroup
          title="生效状态"
          options={["生效中", "未激活"]}
          value={filters.status === "all" ? null : filters.status}
          onChange={(value) =>
            onChange({ ...filters, status: (value as KnowledgeFilters["status"]) ?? "all" })
          }
        />

        <FilterGroup
          title="分类"
          options={categories}
          value={filters.category}
          onChange={(value) => onChange({ ...filters, category: value })}
        />

        <FilterGroup
          title="适用品种"
          options={speciesOptions}
          value={filters.species}
          onChange={(value) => onChange({ ...filters, species: value })}
        />
      </div>
    </div>
  );
}
