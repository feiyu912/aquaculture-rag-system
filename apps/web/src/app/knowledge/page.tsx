"use client";

import * as React from "react";
import { useQuery } from "@tanstack/react-query";

import { AppShell } from "@/components/layout/app-shell";
import {
  EMPTY_FILTERS,
  KnowledgeFilterPanel,
  type KnowledgeFilters,
} from "@/components/knowledge/knowledge-filter-panel";
import { KnowledgeWorkspace } from "@/components/knowledge/knowledge-workspace";
import { useDocuments } from "@/hooks/use-documents";
import { documentsApi } from "@/lib/api/documents";

export default function KnowledgePage() {
  const [filters, setFilters] = React.useState<KnowledgeFilters>(EMPTY_FILTERS);
  const { data: documents } = useDocuments();
  const { data: speciesOptions } = useQuery({
    queryKey: ["species"],
    queryFn: documentsApi.species,
    staleTime: 60_000,
  });

  const categories = React.useMemo(() => {
    const set = new Set<string>();
    for (const document of documents ?? []) set.add(document.category);
    set.add("未分类");
    return Array.from(set);
  }, [documents]);

  return (
    <AppShell
      contextLabel="筛选"
      context={
        <KnowledgeFilterPanel
          filters={filters}
          onChange={setFilters}
          categories={categories}
          speciesOptions={(speciesOptions ?? []).filter((item) => item !== "通用")}
        />
      }
    >
      <KnowledgeWorkspace filters={filters} onFiltersChange={setFilters} />
    </AppShell>
  );
}
