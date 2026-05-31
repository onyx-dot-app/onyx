// Lightweight mobile source-metadata helpers.
//
// Mobile has no curated `SourceMetadata` map (icons/displayNames) like web. This
// module builds a minimal equivalent keyed by the raw source string, plus:
//   - getConfiguredSources: dedup + normalize raw source strings (CC-pairs +
//     federated connectors) into MobileSource[] (mirrors web getConfiguredSources).
//   - buildFilters: ported from web/src/lib/search/utils.ts (sources-only; mobile
//     has no doc-set/time/tag pickers yet).

import { humanizeSourceType } from "@/components/message/sources/sourceInfo";
import type { Filters } from "@/lib/types";

/** Lightweight mobile source descriptor (no icon component map on mobile). */
export interface MobileSource {
  /** Source string with the "federated_" prefix stripped, e.g. "google_drive". */
  internalName: string;
  /** Humanized label, e.g. "Google Drive". */
  displayName: string;
  /** Dedup key: internalName with the "federated_" prefix stripped. */
  uniqueKey: string;
}

/**
 * Dedup + normalize raw source strings (from CC-pairs + federated connectors)
 * into MobileSource[]. Mirrors web getConfiguredSources: strips "federated_"
 * and dedups by clean name.
 */
export function getConfiguredSources(
  availableSources: string[]
): MobileSource[] {
  const seen = new Set<string>();
  const out: MobileSource[] = [];
  for (const raw of availableSources) {
    const cleanName = raw.replace("federated_", "");
    if (seen.has(cleanName)) continue;
    seen.add(cleanName);
    out.push({
      internalName: cleanName,
      displayName: humanizeSourceType(cleanName),
      uniqueKey: cleanName,
    });
  }
  return out;
}

/**
 * Ported from web/src/lib/search/utils.ts (sources-only; mobile has no
 * doc-set/time/tag pickers yet). NOTE: the mobile `Filters` type (search.ts) has
 * no `tags` field — unlike the web object literal — so `tags` is intentionally
 * omitted here to satisfy the type exactly.
 */
export function buildFilters(sources: MobileSource[]): Filters {
  return {
    source_type:
      sources.length > 0 ? sources.map((s) => s.internalName) : null,
    document_set: null,
    time_cutoff: null,
  };
}
