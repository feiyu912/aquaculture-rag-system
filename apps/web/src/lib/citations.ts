import type { Source } from "@/lib/api/types";

/**
 * Rewrite inline citation markers into markdown links so react-markdown can
 * render them as interactive chips.
 *
 * The backend emits `[S1]`, `[S1,S2]`, `[1]` and `【S1】`; we normalise all
 * of them to `[S1](#cite-1)` links which the `a` renderer maps back to a
 * citation chip.
 */
export function injectCitationLinks(text: string): string {
  if (!text) return "";
  return text.replace(/[【\[]([S]?\d+(?:\s*[,，、]\s*[S]?\d+)*)[】\]]/g, (match, body: string) => {
    const indices = body
      .split(/[,，、]/)
      .map((part) => part.trim().replace(/^S/i, ""))
      .filter(Boolean);
    if (!indices.length || !indices.every((value) => /^\d+$/.test(value))) return match;
    return indices.map((value) => `[S${value}](#cite-${value})`).join("");
  });
}

export const CITATION_HREF_PREFIX = "#cite-";

export function parseCitationHref(href: string | undefined): number | null {
  if (!href || !href.startsWith(CITATION_HREF_PREFIX)) return null;
  const value = Number.parseInt(href.slice(CITATION_HREF_PREFIX.length), 10);
  return Number.isFinite(value) ? value : null;
}

export function findSource(sources: Source[], index: number): Source | undefined {
  return sources.find((source) => source.index === index);
}

export function sourceLabel(source: Source): string {
  return source.source_id || `S${source.index}`;
}
