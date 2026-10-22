"use client";

import * as React from "react";
import { Filter, RotateCcw, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Separator } from "@/components/ui/separator";
import type { CatalogFacets, FacetValue } from "@/lib/api/types";
import {
  AUTHORITY_LABELS,
  DOCUMENT_TYPE_LABELS,
  DOC_STATUS_LABELS,
  REVIEW_STATE_LABELS,
} from "@/lib/labels";
import { cn } from "@/lib/utils";

export type PublishedFilter = "all" | "published" | "unpublished";

export interface KnowledgeFilters {
  query: string;
  /** null = all non-deleted records. */
  status: string | null;
  published: PublishedFilter;
  technicalReview: string | null;
  domainReview: string | null;
  documentType: string | null;
  sourceType: string | null;
  authorityLevel: string | null;
  language: string | null;
  species: string | null;
  category: string | null;
  license: string | null;
  sort: string;
  page: number;
  pageSize: number;
}

export const EMPTY_FILTERS: KnowledgeFilters = {
  query: "",
  status: null,
  published: "all",
  technicalReview: null,
  domainReview: null,
  documentType: null,
  sourceType: null,
  authorityLevel: null,
  language: null,
  species: null,
  category: null,
  license: null,
  sort: "created_desc",
  page: 1,
  pageSize: 25,
};

export const SORT_OPTIONS = [
  { value: "created_desc", label: "最新入库" },
  { value: "created_asc", label: "最早入库" },
  { value: "updated_desc", label: "最近更新" },
  { value: "title_asc", label: "标题 A→Z" },
  { value: "year_desc", label: "出版年份新→旧" },
] as const;

const LANGUAGE_LABELS: Record<string, string> = {
  zh: "中文",
  en: "英文",
  ja: "日文",
  未标注: "未标注",
};

function facetOptions(
  values: FacetValue[] | undefined,
  labels?: Record<string, string>,
): { value: string; label: string; count: number }[] {
  return (values ?? []).map((item) => ({
    value: item.value,
    label: item.label ?? labels?.[item.value] ?? item.value,
    count: item.count,
  }));
}

export function FilterGroup({
  title,
  options,
  value,
  onChange,
  allLabel = "全部",
  allCount,
}: {
  title: string;
  options: { value: string; label: string; count?: number }[];
  value: string | null;
  onChange: (value: string | null) => void;
  allLabel?: string;
  allCount?: number;
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
          <span>{allLabel}</span>
          {allCount !== undefined ? (
            <span className="text-[11px] tabular-nums text-subtle-foreground">{allCount}</span>
          ) : null}
        </button>
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(value === option.value ? null : option.value)}
            className={cn(
              "flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-colors duration-150",
              value === option.value
                ? "bg-primary-soft font-medium text-primary-soft-fg"
                : "text-muted-foreground hover:bg-surface-muted hover:text-foreground",
            )}
          >
            <span className="truncate">{option.label}</span>
            {option.count !== undefined && (
              <span className="shrink-0 text-[11px] tabular-nums text-subtle-foreground">
                {option.count}
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
  facets,
  loading,
}: {
  filters: KnowledgeFilters;
  onChange: (filters: KnowledgeFilters) => void;
  facets?: CatalogFacets;
  loading?: boolean;
}) {
  const dirty =
    filters.query !== "" ||
    filters.status !== null ||
    filters.published !== "all" ||
    filters.technicalReview !== null ||
    filters.domainReview !== null ||
    filters.documentType !== null ||
    filters.sourceType !== null ||
    filters.authorityLevel !== null ||
    filters.language !== null ||
    filters.species !== null ||
    filters.category !== null ||
    filters.license !== null;

  const nonDeletedCount = React.useMemo(
    () =>
      (facets?.status ?? [])
        .filter((item) => item.value !== "deleted")
        .reduce((sum, item) => sum + item.count, 0),
    [facets],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 space-y-3 px-3 pb-3 pt-3.5">
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-subtle-foreground" />
            <Input
              value={filters.query}
              onChange={(event) =>
                onChange({ ...filters, query: event.target.value, page: 1 })
              }
              placeholder="搜索标题、机构、URL"
              className="h-8 pl-8 text-[12.5px]"
              aria-label="搜索文档"
            />
          </div>
          {dirty && (
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="重置筛选"
              onClick={() => onChange({ ...EMPTY_FILTERS, pageSize: filters.pageSize })}
            >
              <RotateCcw className="size-3.5" />
            </Button>
          )}
        </div>
        <p className="text-[11px] leading-4 text-subtle-foreground">
          筛选在服务端执行；统计为全库聚合，不按当前页推算。
        </p>
      </div>

      <Separator />

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-3 py-4">
        <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-muted-foreground">
          <Filter className="size-3.5" />
          筛选
        </div>

        <FilterGroup
          title="发布状态"
          options={[
            { value: "published", label: "已发布（active + verified）" },
            { value: "unpublished", label: "未发布（含 staging）" },
          ]}
          value={filters.published === "all" ? null : filters.published}
          onChange={(value) =>
            onChange({
              ...filters,
              published: (value as PublishedFilter | null) ?? "all",
              page: 1,
            })
          }
        />

        <FilterGroup
          title="文档状态"
          options={[
            { value: "active", label: DOC_STATUS_LABELS.active, count: facetCount(facets, "status", "active") },
            { value: "staging", label: DOC_STATUS_LABELS.staging, count: facetCount(facets, "status", "staging") },
            { value: "failed", label: DOC_STATUS_LABELS.failed, count: facetCount(facets, "status", "failed") },
            { value: "deleted", label: DOC_STATUS_LABELS.deleted, count: facetCount(facets, "status", "deleted") },
          ]}
          value={filters.status}
          allLabel="全部（未删除）"
          allCount={nonDeletedCount}
          onChange={(value) => onChange({ ...filters, status: value, page: 1 })}
        />

        <FilterGroup
          title="材料性质"
          options={facetOptions(facets?.document_type, DOCUMENT_TYPE_LABELS)}
          value={filters.documentType}
          onChange={(value) => onChange({ ...filters, documentType: value, page: 1 })}
        />

        <FilterGroup
          title="来源格式"
          options={[
            { value: "pdf", label: "PDF", count: facetCount(facets, "source_type", "pdf") },
            { value: "html", label: "网页", count: facetCount(facets, "source_type", "html") },
          ]}
          value={filters.sourceType}
          onChange={(value) => onChange({ ...filters, sourceType: value, page: 1 })}
        />

        <FilterGroup
          title="效力等级"
          options={facetOptions(facets?.authority_level, AUTHORITY_LABELS)}
          value={filters.authorityLevel}
          onChange={(value) => onChange({ ...filters, authorityLevel: value, page: 1 })}
        />

        <FilterGroup
          title="技术检查"
          options={facetOptions(facets?.technical_review_status, REVIEW_STATE_LABELS)}
          value={filters.technicalReview}
          onChange={(value) => onChange({ ...filters, technicalReview: value, page: 1 })}
        />

        <FilterGroup
          title="领域审核"
          options={facetOptions(facets?.domain_review_status, REVIEW_STATE_LABELS)}
          value={filters.domainReview}
          onChange={(value) => onChange({ ...filters, domainReview: value, page: 1 })}
        />

        <FilterGroup
          title="语言"
          options={facetOptions(facets?.language, LANGUAGE_LABELS)}
          value={filters.language}
          onChange={(value) => onChange({ ...filters, language: value, page: 1 })}
        />

        <FilterGroup
          title="许可证"
          options={facetOptions(facets?.license)}
          value={filters.license}
          onChange={(value) => onChange({ ...filters, license: value, page: 1 })}
        />

        <FilterGroup
          title="分类"
          options={facetOptions(facets?.category)}
          value={filters.category}
          onChange={(value) => onChange({ ...filters, category: value, page: 1 })}
        />

        <FilterGroup
          title="适用品种"
          options={(facets?.species ?? [])
            .filter((item) => item.value !== "通用")
            .map((item) => ({ value: item.value, label: item.value, count: item.count }))}
          value={filters.species}
          onChange={(value) => onChange({ ...filters, species: value, page: 1 })}
        />

        <FilterGroup
          title="排序"
          options={SORT_OPTIONS.filter((item) => item.value !== "created_desc").map((item) => ({
            value: item.value,
            label: item.label,
          }))}
          value={filters.sort === "created_desc" ? null : filters.sort}
          allLabel="最新入库"
          onChange={(value) =>
            onChange({ ...filters, sort: value ?? "created_desc", page: 1 })
          }
        />

        {loading ? (
          <p className="px-2 text-[11px] text-subtle-foreground">筛选项加载中…</p>
        ) : null}
      </div>
    </div>
  );
}

function facetCount(
  facets: CatalogFacets | undefined,
  key: keyof CatalogFacets,
  value: string,
): number | undefined {
  return facets?.[key]?.find((item) => item.value === value)?.count;
}
