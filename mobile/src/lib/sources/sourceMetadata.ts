// Mobile has no curated `SourceMetadata` map (icons/displayNames) like web, so
// this builds a minimal equivalent keyed by the raw source string.

import { humanizeSourceType } from "@/components/message/sources/sourceInfo";
import type { Filters } from "@/lib/types";

export interface MobileSource {
  internalName: string;
  displayName: string;
  uniqueKey: string;
}

// Mirrors web getConfiguredSources: strips "federated_" and dedups by clean name.
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

// Mirrors web search/utils.ts (sources-only). `tags` is omitted because the
// mobile `Filters` type has no such field, unlike the web object literal.
export function buildFilters(sources: MobileSource[]): Filters {
  return {
    source_type:
      sources.length > 0 ? sources.map((s) => s.internalName) : null,
    document_set: null,
    time_cutoff: null,
  };
}
