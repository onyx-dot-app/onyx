"use client";

import { useMemo } from "react";
import { Text } from "@opal/components";
import { SvgFileText } from "@opal/icons";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

interface SearchHit {
  path: string;
  line?: string;
  snippet?: string;
}

interface GroupedHits {
  path: string;
  hits: SearchHit[];
}

/**
 * Parse the raw search output into structured hits.
 *
 * - glob: rawOutput is one file path per line
 * - grep: rawOutput is `file:line:content` per line (best-effort split — files
 *   on Unix never contain a colon in the path, so split on first two colons)
 */
function parseHits(rawOutput: string): SearchHit[] {
  if (!rawOutput) return [];
  const lines = rawOutput.split("\n").filter((l) => l.trim().length > 0);
  return lines.map((line) => {
    const firstColon = line.indexOf(":");
    if (firstColon === -1) {
      return { path: line };
    }
    const secondColon = line.indexOf(":", firstColon + 1);
    if (secondColon === -1) {
      return {
        path: line.slice(0, firstColon),
        line: line.slice(firstColon + 1),
      };
    }
    const path = line.slice(0, firstColon);
    const lineNum = line.slice(firstColon + 1, secondColon);
    const snippet = line.slice(secondColon + 1);
    if (!/^\d+$/.test(lineNum)) {
      return { path: line };
    }
    return { path, line: lineNum, snippet };
  });
}

/** Group hits by file path while preserving first-seen order. */
function groupByFile(hits: SearchHit[]): GroupedHits[] {
  const seen = new Map<string, SearchHit[]>();
  for (const hit of hits) {
    const list = seen.get(hit.path);
    if (list) {
      list.push(hit);
    } else {
      seen.set(hit.path, [hit]);
    }
  }
  return Array.from(seen.entries()).map(([path, hits]) => ({ path, hits }));
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Split a snippet by occurrences of `pattern` so we can <mark> the matches.
 * Returns alternating [plain, match, plain, match, ...] segments. Falls back
 * to a single plain segment when the pattern is empty or invalid.
 */
function highlightSegments(
  snippet: string,
  pattern: string | undefined
): Array<{ text: string; match: boolean }> {
  if (!pattern || !snippet) return [{ text: snippet, match: false }];
  try {
    const re = new RegExp(escapeRegex(pattern), "gi");
    const segments: Array<{ text: string; match: boolean }> = [];
    let last = 0;
    let m: RegExpExecArray | null;
    while ((m = re.exec(snippet)) !== null) {
      if (m.index > last) {
        segments.push({ text: snippet.slice(last, m.index), match: false });
      }
      segments.push({ text: m[0], match: true });
      last = m.index + m[0].length;
      if (m[0].length === 0) re.lastIndex++;
    }
    if (last < snippet.length) {
      segments.push({ text: snippet.slice(last), match: false });
    }
    return segments.length > 0 ? segments : [{ text: snippet, match: false }];
  } catch {
    return [{ text: snippet, match: false }];
  }
}

/**
 * SearchBody - File search results grouped by file.
 *
 * UX modeled after VSCode / GitHub code search: each file is a section
 * with a header row (icon + path + match count); matched lines are
 * indented underneath as `LINE   snippet`, with the searched pattern
 * highlighted via <mark>.
 */
export default function SearchBody({ toolCall }: ToolCardBodyProps) {
  const hits = useMemo(
    () => parseHits(toolCall.rawOutput),
    [toolCall.rawOutput]
  );
  const grouped = useMemo(() => groupByFile(hits), [hits]);
  const pattern = toolCall.description || undefined;

  if (grouped.length === 0) {
    return (
      <div className="px-3 py-1">
        <Text font="main-ui-muted" color="text-02">
          No matches
        </Text>
      </div>
    );
  }

  return (
    <div className="overflow-y-auto max-h-[24rem] divide-y divide-border-01">
      {grouped.map((group) => {
        const hasSnippets = group.hits.some((h) => h.snippet);
        return (
          <div key={group.path}>
            <div className="px-3 py-1 flex items-center gap-2 bg-background-tint-01 min-w-0">
              <SvgFileText className="size-3.5 stroke-text-03 shrink-0" />
              <span className="min-w-0 truncate flex-1">
                <Text font="secondary-mono" color="text-04" nowrap>
                  {group.path}
                </Text>
              </span>
              {hasSnippets && group.hits.length > 1 && (
                <span className="shrink-0">
                  <Text font="secondary-mono-label" color="text-02">
                    {`${group.hits.length} matches`}
                  </Text>
                </span>
              )}
            </div>
            {hasSnippets &&
              group.hits.map((hit, idx) => {
                const segments = highlightSegments(hit.snippet ?? "", pattern);
                return (
                  <div
                    key={idx}
                    className="px-3 py-0.5 pl-9 flex items-baseline gap-3 min-w-0 hover:bg-background-tint-01 transition-colors"
                  >
                    <span className="shrink-0 text-right w-8 select-none">
                      <Text font="secondary-mono-label" color="text-02" nowrap>
                        {hit.line ?? ""}
                      </Text>
                    </span>
                    <span
                      className="min-w-0 truncate"
                      style={{
                        fontFamily: "var(--font-dm-mono)",
                        fontSize: "12px",
                      }}
                    >
                      {segments.map((seg, i) =>
                        seg.match ? (
                          <mark
                            key={i}
                            className="bg-status-warning-01 text-text-05 rounded-sm px-0.5"
                          >
                            {seg.text}
                          </mark>
                        ) : (
                          <span key={i} className="text-text-03">
                            {seg.text}
                          </span>
                        )
                      )}
                    </span>
                  </div>
                );
              })}
          </div>
        );
      })}
    </div>
  );
}
