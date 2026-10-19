import { errorHandlingFetcher } from "@/lib/fetcher";
import type { ToolSnapshot } from "@/lib/tools/types";

// ---------------------------------------------------------------------------
// Raw API shape — enriched before anything reads it, so consumers always
// receive a resolved `ToolSnapshot`. For an OpenAPI tool the API's `name` and
// `description` are only stored overrides, possibly empty.
// ---------------------------------------------------------------------------

export type RawToolSnapshot = Omit<
  ToolSnapshot,
  "name_override" | "description_override"
>;

function schemaText(tool: RawToolSnapshot, key: "title" | "description") {
  // Only an OpenAPI tool has its own schema to fall back to.
  if (tool.in_code_tool_id || tool.mcp_server_id != null) return "";
  const value: unknown = tool.definition?.info?.[key];
  return typeof value === "string" ? value : "";
}

/**
 * Resolves an OpenAPI tool's name and description: the stored override, or
 * else its schema's `info.title` and `info.description`. The stored values
 * stay readable as `name_override` and `description_override`.
 */
export function enrichToolSnapshot(tool: RawToolSnapshot): ToolSnapshot {
  const name = tool.name || schemaText(tool, "title");
  return {
    ...tool,
    name,
    display_name: tool.display_name || name,
    description: tool.description || schemaText(tool, "description"),
    name_override: tool.name || null,
    description_override: tool.description || null,
  };
}

/** SWR fetcher for an endpoint that returns a list of tools. */
export async function toolsFetcher(url: string): Promise<ToolSnapshot[]> {
  const tools = await errorHandlingFetcher<RawToolSnapshot[]>(url);
  return tools.map(enrichToolSnapshot);
}

/** An agent, or any record carrying tools, with its tools enriched. */
export function withEnrichedTools<T extends { tools: RawToolSnapshot[] }>(
  record: T
): T & { tools: ToolSnapshot[] } {
  return { ...record, tools: record.tools.map(enrichToolSnapshot) };
}
