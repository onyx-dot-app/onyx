"use client";

import { useMemo } from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import { SvgFileText } from "@opal/icons";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

interface SearchHit {
  path: string;
  line?: string;
  snippet?: string;
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
      // file:line with no content (rare)
      return {
        path: line.slice(0, firstColon),
        line: line.slice(firstColon + 1),
      };
    }
    const path = line.slice(0, firstColon);
    const lineNum = line.slice(firstColon + 1, secondColon);
    const snippet = line.slice(secondColon + 1);
    if (!/^\d+$/.test(lineNum)) {
      // Not a real grep line — treat the whole thing as a path
      return { path: line };
    }
    return { path, line: lineNum, snippet };
  });
}

/**
 * SearchBody - Result list for glob/grep tools.
 *
 * Renders each hit as a row: file icon + path + optional line + snippet.
 */
export default function SearchBody({ toolCall }: ToolCardBodyProps) {
  const hits = useMemo(
    () => parseHits(toolCall.rawOutput),
    [toolCall.rawOutput]
  );

  if (hits.length === 0) {
    return (
      <div className="p-3 rounded-08 border-[0.5px] bg-background-neutral-01 border-border-01">
        <Text font="main-ui-muted" color="text-02">
          No matches
        </Text>
      </div>
    );
  }

  return (
    <div className="rounded-08 border-[0.5px] bg-background-neutral-01 border-border-01 overflow-hidden">
      <div className="overflow-auto max-h-[24rem] divide-y divide-border-01">
        {hits.map((hit, idx) => (
          <div
            key={idx}
            className={cn(
              "px-3 py-2 flex flex-col gap-1",
              "hover:bg-background-tint-02 transition-colors"
            )}
          >
            <div className="flex items-center gap-2 min-w-0">
              <SvgFileText className="size-3.5 stroke-text-03 shrink-0" />
              <span className="truncate min-w-0">
                <Text font="secondary-mono" color="text-04" nowrap>
                  {hit.path}
                </Text>
              </span>
              {hit.line && (
                <span className="shrink-0">
                  <Text font="secondary-mono-label" color="text-02">
                    {`:${hit.line}`}
                  </Text>
                </span>
              )}
            </div>
            {hit.snippet && (
              <div className="pl-5 truncate">
                <Text font="secondary-mono" color="text-03" nowrap>
                  {hit.snippet}
                </Text>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
