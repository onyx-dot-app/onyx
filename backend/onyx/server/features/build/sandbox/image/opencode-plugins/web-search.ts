// A `web_search` tool that searches the web through Onyx's own web search
// (`POST /web-search/search-lite`), so it uses the admin's search provider and
// egress rules, as chat's web search does.
//
// It returns readable text for the model and the structured queries and
// results as the tool part's `metadata`. The api-server copies that metadata
// into the tool call's `_meta.onyx.search` (serve_client._onyx_search_meta), so
// the frontend shows the results without parsing text.
//
// Auth and base URL come from the sandbox's env allowlist: `ONYX_SERVER_URL`
// (the complete API base) and `ONYX_PAT`, the same credentials onyx-cli uses.
//
// Module resolution: see connect-app.ts; the `tool` helper is loaded at
// runtime by absolute path from opencode's bundled SDK.

import type { Plugin } from "@opencode-ai/plugin";
import type { tool as ToolFactory } from "@opencode-ai/plugin/tool";

const SDK_TOOL_PATHS = [
  "/home/sandbox/.opencode/node_modules/@opencode-ai/plugin/dist/tool.js",
  "/home/sandbox/.config/opencode/node_modules/@opencode-ai/plugin/dist/tool.js",
];

// Caps on what is sent back. Every tool-call update repeats the whole object,
// and the final one is saved, so keep it small.
const MAX_RESULTS_PER_QUERY = 10;
const MAX_RESULTS = 20;
const MAX_SNIPPET_CHARS = 300;

interface SearchResult {
  title: string;
  url: string;
  snippet: string;
}

async function loadToolFactory(): Promise<typeof ToolFactory> {
  for (const path of SDK_TOOL_PATHS) {
    try {
      return (await import(path)).tool;
    } catch {
      continue;
    }
  }
  throw new Error("could not resolve the @opencode-ai/plugin tool helper");
}

function asResults(body: unknown): SearchResult[] {
  if (typeof body !== "object" || body === null) return [];
  const results = (body as { results?: unknown }).results;
  if (!Array.isArray(results)) return [];
  const out: SearchResult[] = [];
  for (const item of results) {
    if (typeof item !== "object" || item === null) continue;
    const { title, url, snippet } = item as Record<string, unknown>;
    if (typeof url !== "string" || url.length === 0) continue;
    out.push({
      title: typeof title === "string" && title ? title : url,
      url,
      snippet:
        typeof snippet === "string" ? snippet.slice(0, MAX_SNIPPET_CHARS) : "",
    });
    if (out.length >= MAX_RESULTS) break;
  }
  return out;
}

function formatForModel(results: SearchResult[]): string {
  if (results.length === 0) return "No results found.";
  return results
    .map(
      (result, index) =>
        `${index + 1}. ${result.title}\n${result.url}\n${result.snippet}`
    )
    .join("\n\n");
}

export const WebSearch: Plugin = async () => {
  const tool = await loadToolFactory();

  return {
    tool: {
      web_search: tool({
        description:
          "Search the web. Pass 1-3 short, specific queries; independent " +
          "queries run together. Returns titles, URLs and snippets. To read a " +
          "page, call webfetch on its URL.",
        args: {
          queries: tool.schema
            .array(tool.schema.string().min(1))
            .min(1)
            .max(3)
            .describe("Search queries, e.g. ['react 19 release notes']"),
        },
        async execute(args, context) {
          const base = process.env.ONYX_SERVER_URL;
          const token = process.env.ONYX_PAT;
          if (!base || !token) {
            return "Web search is not available in this session.";
          }

          const response = await fetch(
            `${base.replace(/\/+$/, "")}/web-search/search-lite`,
            {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${token}`,
                "X-Onyx-Authorization": `Bearer ${token}`,
              },
              body: JSON.stringify({
                queries: args.queries,
                max_results: MAX_RESULTS_PER_QUERY,
              }),
              signal: context.abort,
            }
          );
          if (!response.ok) {
            // Tell the model plainly; it can fall back to webfetch.
            return `Web search failed (HTTP ${response.status}). Web search may not be configured; try webfetch on a known URL instead.`;
          }

          const results = asResults(await response.json());
          return {
            output: formatForModel(results),
            metadata: { onyxSearch: { queries: args.queries, results } },
          };
        },
      }),
    },
  };
};

export default WebSearch;
