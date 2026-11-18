"use client";

import { useMemo } from "react";
import { ValidSources } from "@/lib/connectors/types/source";
import { RetrievalBody } from "@/lib/timeline/components/bodies/RetrievalBody";
import { CommandBody } from "@/lib/timeline/components/bodies/CommandBody";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

interface SearchResult {
  title?: string;
  url: string;
  snippet?: string;
}

// URL_RE is stateless — used with .test() in filters. URL_RE_G is the
// /g-flagged variant used with .match() to collect all URLs in a block.
// A single shared /g constant would let .test() leak lastIndex between
// iterations and misclassify every other URL line.
const URL_RE = /https?:\/\/[^\s)]+/;
const URL_RE_G = new RegExp(URL_RE, "g");

/**
 * Best-effort parser for websearch raw output. Handles two common shapes:
 *  1. Markdown-style results: "## Title\nurl\nsnippet"
 *  2. Plain text with URLs embedded; one result per blank-line block.
 */
function parseResults(rawOutput: string): SearchResult[] {
  if (!rawOutput.trim()) return [];

  const blocks = rawOutput
    .split(/\n\s*\n/)
    .map((b) => b.trim())
    .filter(Boolean);

  const results: SearchResult[] = [];
  for (const block of blocks) {
    const lines = block
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (lines.length === 0) continue;
    const urls = block.match(URL_RE_G);
    if (!urls || urls.length === 0) continue;
    const url = urls[0]!;
    // Overlapping queries can return the same page; it shows once.
    if (results.some((result) => result.url === url)) continue;

    // Heuristics: first non-URL line is the title; subsequent non-URL lines are snippet
    const nonUrlLines = lines.filter((l) => !URL_RE.test(l));
    const title = nonUrlLines[0]?.replace(/^#+\s*/, "");
    const snippet = nonUrlLines.slice(1).join(" ") || undefined;
    results.push({ title, url, snippet });
  }

  return results;
}

function domainFromUrl(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return url;
  }
}

/**
 * WebSearchBody - The websearch tool's queries and the results it read, in the
 * shared retrieval layout: from `_meta.onyx.search` when the backend sends
 * them, otherwise parsed from the text output. Output that parses into no results shows as a
 * `CommandBody`: the query, then the raw output.
 */
export default function WebSearchBody({ toolCall }: ToolCardBodyProps) {
  const results = useMemo(
    () => parseResults(toolCall.rawOutput),
    [toolCall.rawOutput]
  );
  const isComplete =
    toolCall.status !== "pending" && toolCall.status !== "in_progress";

  // Onyx's web_search sends its queries and results in `_meta.onyx`: no text
  // to parse. Older rows and opencode's own websearch fall through to parsing.
  const search = toolCall.onyxSearch;
  if (search) {
    return (
      <RetrievalBody
        queries={search.queries}
        // `/search-lite` does not dedupe across queries; a page shows once.
        results={search.results
          .filter(
            (result, index, all) =>
              all.findIndex((other) => other.url === result.url) === index
          )
          .map((result) => ({
            id: result.url,
            title: result.title,
            sourceType: ValidSources.Web,
            sourceUrl: result.url,
            description: result.snippet || undefined,
          }))}
        isComplete={isComplete}
      />
    );
  }

  // Output that parses into results reads like chat's web search; output
  // that does not (plain text) shows under the query, like glob and grep.
  if (results.length === 0 && toolCall.rawOutput) {
    return (
      <CommandBody
        command={toolCall.description}
        title={toolCall.toolName ?? toolCall.title}
        output={toolCall.rawOutput}
        emptyLabel=""
      />
    );
  }

  return (
    <RetrievalBody
      queries={toolCall.description ? [toolCall.description] : []}
      results={results.map((result) => ({
        id: result.url,
        title: result.title ?? domainFromUrl(result.url),
        sourceType: ValidSources.Web,
        sourceUrl: result.url,
        description: result.snippet,
      }))}
      isComplete={isComplete}
    />
  );
}
