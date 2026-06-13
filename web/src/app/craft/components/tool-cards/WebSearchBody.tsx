"use client";

import { useMemo } from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgGlobe } from "@opal/icons";
import ToolCardSurface, {
  ToolCardSection,
} from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

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
 * WebSearchBody - Result cards for the websearch tool.
 *
 * Falls back to a single block of raw output when no structured results can
 * be parsed.
 */
export default function WebSearchBody({ toolCall }: ToolCardBodyProps) {
  const results = useMemo(
    () => parseResults(toolCall.rawOutput),
    [toolCall.rawOutput]
  );

  if (results.length === 0) {
    return (
      <ToolCardSurface>
        <ToolCardSection className="whitespace-pre-wrap wrap-break-word">
          <Text as="p" font="secondary-mono" color="text-03">
            {toolCall.rawOutput || "No results"}
          </Text>
        </ToolCardSection>
      </ToolCardSurface>
    );
  }

  return (
    <ToolCardSurface>
      <div className="divide-y divide-border-01">
        {results.map((result, idx) => (
          <div
            key={idx}
            className={cn(
              "py-2 px-3 flex flex-col gap-1",
              "hover:bg-background-tint-01 transition-colors"
            )}
          >
            <div className="flex items-center gap-2 min-w-0">
              <SvgGlobe className="size-3.5 stroke-text-03 shrink-0" />
              <span className="truncate min-w-0">
                <Text font="main-ui-action" color="text-04" nowrap>
                  {result.title ?? domainFromUrl(result.url)}
                </Text>
              </span>
            </div>
            <div className="pl-5 truncate">
              <Text font="secondary-mono" color="text-02" nowrap>
                {result.url}
              </Text>
            </div>
            {result.snippet && (
              <div className="pl-5">
                <Text font="secondary-body" color="text-03">
                  {result.snippet}
                </Text>
              </div>
            )}
          </div>
        ))}
      </div>
    </ToolCardSurface>
  );
}
