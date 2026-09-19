import type { Tag, ValidSources } from "@/lib/types";
import type { MinimalAgent } from "@/lib/agents/types";
import type { ChatSearchFilters } from "@/lib/tools/types";
import { isAssistant } from "@/lib/agents/utils";
import { SEARCH_TOOL_ID } from "@/lib/tools/constants";
import type { SourceMetadata } from "@/lib/search/interfaces";
import type { SearchFiltersRequest } from "@/lib/searchFilters/types";

/**
 * Freezes a live selection into the shape the backend receives.
 *
 * `sources` distinguishes "no filter" from "none selected": `null` sends no
 * source filter at all, while an empty array is sent as an explicitly empty
 * list, which the backend answers with no results.
 */
export function buildFilters(
  sources: SourceMetadata[] | null,
  documentSets: readonly string[],
  timeRange: { from: Date | string } | null,
  tags: readonly Tag[]
): SearchFiltersRequest {
  return {
    source_type: sources ? sources.map((source) => source.internalName) : null,
    document_set: documentSets.length > 0 ? [...documentSets] : null,
    updated_at_range: timeRange?.from
      ? { start: timeRange.from, end: null }
      : null,
    tags: [...tags],
  };
}

/**
 * The complete set of sources one agent can search over. An assistant reads
 * the workspace's connectors; a custom agent declaring `knowledge_sources`
 * reads those, except that declaring none while carrying the search tool
 * means "everything accessible", not "nothing".
 */
export function effectiveAvailableSourcesFor(
  agent: MinimalAgent,
  availableSources: ValidSources[]
): ValidSources[] {
  if (agentDeclaresOwnSources(agent)) {
    return (agent.knowledge_sources ?? []) as ValidSources[];
  }
  return availableSources;
}

/**
 * Whether this agent's `knowledge_sources` is its complete roster. False for
 * assistants and for custom agents declaring nothing while carrying the
 * search tool, where "nothing declared" means "everything accessible".
 */
export function agentDeclaresOwnSources(agent: MinimalAgent): boolean {
  if (isAssistant(agent)) return false;
  const declared = agent.knowledge_sources ?? [];
  if (declared.length > 0) return true;
  const hasSearchTool = agent.tools.some(
    (tool) => tool.in_code_tool_id === SEARCH_TOOL_ID
  );
  return !hasSearchTool;
}

/**
 * Resolves a chat's stored source selection against the sources an agent can
 * reach. An untouched selection (`null`) sends no source filter, which also
 * keeps a send that races the connector fetch from narrowing to an
 * accidental empty list. An explicit selection intersects with what is
 * configured, so a connector removed since the pick silently drops out.
 */
export function selectedSourcesFrom(
  filters: ChatSearchFilters,
  configuredSources: SourceMetadata[]
): SourceMetadata[] | null {
  const selected = filters.selectedSources;
  if (selected === null) return null;
  return configuredSources.filter(
    (source) =>
      source.uniqueKey !== undefined && selected.includes(source.uniqueKey)
  );
}

/**
 * One source toggled within a stored selection, normalized at the edit
 * boundary: the untouched sentinel materialises into an explicit list for
 * the edit, and a result covering every configured source collapses back to
 * `null` — "all" keeps one representation, and it stays dynamic, so a
 * connector added later is on.
 */
export function toggleSourceSelection(
  selectedSources: readonly string[] | null,
  uniqueKey: string,
  configuredKeys: readonly string[]
): readonly string[] | null {
  const selected = selectedSources ?? configuredKeys;
  const next = selected.includes(uniqueKey)
    ? selected.filter((key) => key !== uniqueKey)
    : [...selected, uniqueKey];
  return normalizeSourceSelection(next, configuredKeys);
}

/**
 * The edit-boundary half of the sentinel invariant on its own: an explicit
 * selection covering every configured source collapses to `null`, so "all"
 * has one representation and stays dynamic. Every write of an explicit
 * selection goes through this, whichever surface produced it.
 */
export function normalizeSourceSelection(
  selected: readonly string[],
  configuredKeys: readonly string[]
): readonly string[] | null {
  const coversAll =
    configuredKeys.length > 0 &&
    configuredKeys.every((key) => selected.includes(key));
  return coversAll ? null : selected;
}
