"use client";

import * as React from "react";

import { AppShell } from "@/components/layout/app-shell";
import {
  EMPTY_FILTERS,
  KnowledgeFilterPanel,
  type KnowledgeFilters,
} from "@/components/knowledge/knowledge-filter-panel";
import { KnowledgeWorkspace } from "@/components/knowledge/knowledge-workspace";
import { useCatalogFacets } from "@/hooks/use-management";

export default function KnowledgePage() {
  const [tab, setTab] = React.useState<"documents" | "qa">("documents");
  const [filters, setFilters] = React.useState<KnowledgeFilters>(EMPTY_FILTERS);
  const { data: facets, isLoading: facetsLoading } = useCatalogFacets();

  return (
    <AppShell
      contextLabel={tab === "documents" ? "筛选" : "用途"}
      context={
        tab === "documents" ? (
          <KnowledgeFilterPanel
            filters={filters}
            onChange={setFilters}
            facets={facets}
            loading={facetsLoading}
          />
        ) : (
          <div className="space-y-4 px-4 py-4 text-[12px] leading-5 text-muted-foreground">
            <div>
              <p className="text-[13px] font-medium text-foreground">相似问题检索</p>
              <p className="mt-1">
                HF 问答数据用于匹配相近的既有问题，为查询扩展与候选回答提供线索。
              </p>
            </div>
            <div>
              <p className="text-[13px] font-medium text-foreground">回答依据</p>
              <p className="mt-1">
                最终回答以原始文献证据为准；问答数据仅作检索与术语参考，不替代专业文献。
              </p>
            </div>
            <div>
              <p className="text-[13px] font-medium text-foreground">数据范围</p>
              <p className="mt-1">
                中文农林牧渔问答中的水产养殖子集，以及英文水产问答数据集。
              </p>
            </div>
          </div>
        )
      }
    >
      <KnowledgeWorkspace
        filters={filters}
        onFiltersChange={setFilters}
        tab={tab}
        onTabChange={setTab}
      />
    </AppShell>
  );
}