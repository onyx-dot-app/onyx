"use client";

import { useMemo, useState } from "react";
import { cn } from "@opal/utils";
import { Text, Button } from "@opal/components";
import { SvgColumn, SvgMenu } from "@opal/icons";
import ToolCardSurface from "@/app/craft/components/tool-cards/ToolCardSurface";
import type { ToolCardBodyProps } from "@/app/craft/components/tool-cards/interfaces";

type DiffLineType = "added" | "removed" | "unchanged" | "header";

interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLineNum?: number;
  newLineNum?: number;
}

const SIDE_BY_SIDE_AUTO_THRESHOLD = 20;
const BLANK = " ";

function computeDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");
  const result: DiffLine[] = [];

  // Last-occurrence index per unique line, so the "exists later" check
  // below is O(1) instead of O(n) via slice().includes() — the prior
  // form made computeDiff O(n²) on large diffs.
  const lastOldIdxOf = new Map<string, number>();
  oldLines.forEach((l, i) => lastOldIdxOf.set(l, i));
  const lastNewIdxOf = new Map<string, number>();
  newLines.forEach((l, i) => lastNewIdxOf.set(l, i));

  let oldIdx = 0;
  let newIdx = 0;
  let oldLineNum = 1;
  let newLineNum = 1;

  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    const oldLine: string | undefined = oldLines[oldIdx];
    const newLine: string | undefined = newLines[newIdx];

    if (oldIdx >= oldLines.length || oldLine === undefined) {
      result.push({
        type: "added",
        content: newLine ?? "",
        newLineNum: newLineNum++,
      });
      newIdx++;
    } else if (newIdx >= newLines.length || newLine === undefined) {
      result.push({
        type: "removed",
        content: oldLine,
        oldLineNum: oldLineNum++,
      });
      oldIdx++;
    } else if (oldLine === newLine) {
      result.push({
        type: "unchanged",
        content: oldLine,
        oldLineNum: oldLineNum++,
        newLineNum: newLineNum++,
      });
      oldIdx++;
      newIdx++;
    } else {
      const oldExistsLaterInNew = (lastNewIdxOf.get(oldLine) ?? -1) > newIdx;
      const newExistsLaterInOld = (lastOldIdxOf.get(newLine) ?? -1) > oldIdx;

      if (!oldExistsLaterInNew && newExistsLaterInOld) {
        result.push({
          type: "removed",
          content: oldLine,
          oldLineNum: oldLineNum++,
        });
        oldIdx++;
      } else if (oldExistsLaterInNew && !newExistsLaterInOld) {
        result.push({
          type: "added",
          content: newLine,
          newLineNum: newLineNum++,
        });
        newIdx++;
      } else {
        result.push({
          type: "removed",
          content: oldLine,
          oldLineNum: oldLineNum++,
        });
        result.push({
          type: "added",
          content: newLine,
          newLineNum: newLineNum++,
        });
        oldIdx++;
        newIdx++;
      }
    }
  }
  return result;
}

function collapseUnchanged(
  lines: DiffLine[],
  contextLines: number = 3
): DiffLine[] {
  const result: DiffLine[] = [];
  const changeIndices: number[] = [];

  lines.forEach((line, idx) => {
    if (line.type === "added" || line.type === "removed") {
      changeIndices.push(idx);
    }
  });

  if (changeIndices.length === 0) {
    if (lines.length > 10) {
      return [{ type: "header", content: `${lines.length} unchanged lines` }];
    }
    return lines;
  }

  const showIndices = new Set<number>();
  changeIndices.forEach((idx) => {
    for (
      let i = Math.max(0, idx - contextLines);
      i <= Math.min(lines.length - 1, idx + contextLines);
      i++
    ) {
      showIndices.add(i);
    }
  });

  const pushSkippedHeader = (count: number) => {
    if (count <= 0) return;
    result.push({
      type: "header",
      content: `${count} unchanged line${count > 1 ? "s" : ""}`,
    });
  };

  let lastShownIdx = -1;
  lines.forEach((line, idx) => {
    if (showIndices.has(idx)) {
      // Leading skipped block when the first shown index is past line 0.
      if (lastShownIdx === -1 && idx > 0) {
        pushSkippedHeader(idx);
      } else if (lastShownIdx !== -1 && idx - lastShownIdx > 1) {
        pushSkippedHeader(idx - lastShownIdx - 1);
      }
      result.push(line);
      lastShownIdx = idx;
    }
  });
  // Trailing skipped block when the last shown index is before the end.
  if (lastShownIdx !== -1 && lastShownIdx < lines.length - 1) {
    pushSkippedHeader(lines.length - 1 - lastShownIdx);
  }
  return result;
}

type DiffTextColor = "text-02" | "text-03" | "text-04";

function lineRowClass(type: DiffLineType): string {
  switch (type) {
    case "added":
      return "bg-status-success-01";
    case "removed":
      return "bg-status-error-01";
    case "header":
      return "bg-background-tint-02 italic text-center";
    default:
      return "";
  }
}

function linePrefix(type: DiffLineType): { glyph: string; color: string } {
  if (type === "added") return { glyph: "+", color: "text-status-success-05" };
  if (type === "removed") return { glyph: "-", color: "text-status-error-05" };
  return { glyph: BLANK, color: "text-text-03" };
}

function lineTextColor(type: DiffLineType): DiffTextColor {
  if (type === "header") return "text-02";
  if (type === "unchanged") return "text-03";
  return "text-04";
}

function UnifiedDiff({ lines }: { lines: DiffLine[] }) {
  return (
    <div className="overflow-auto max-h-[24rem]">
      {lines.map((line, idx) => {
        const prefix = linePrefix(line.type);
        return (
          <div
            key={idx}
            className={cn(
              "px-2 py-0.5 flex gap-2 items-baseline",
              lineRowClass(line.type)
            )}
          >
            {line.type !== "header" && (
              <span className={cn("select-none shrink-0", prefix.color)}>
                <Text font="secondary-mono" color="inherit">
                  {prefix.glyph}
                </Text>
              </span>
            )}
            <span className="min-w-0 flex-1 whitespace-pre-wrap wrap-break-word block">
              <Text font="secondary-mono" color={lineTextColor(line.type)}>
                {line.content || (line.type === "header" ? "" : BLANK)}
              </Text>
            </span>
          </div>
        );
      })}
    </div>
  );
}

function SideBySideDiff({ lines }: { lines: DiffLine[] }) {
  return (
    <div className="overflow-auto max-h-[24rem] grid grid-cols-2 divide-x divide-border-01">
      <div>
        {lines.map((line, idx) => {
          const isHeader = line.type === "header";
          const showRemoved = line.type === "removed";
          const content = line.type === "added" ? BLANK : line.content || BLANK;
          return (
            <div
              key={`l-${idx}`}
              className={cn(
                "px-2 py-0.5 whitespace-pre-wrap wrap-break-word",
                showRemoved && "bg-status-error-01",
                isHeader && "bg-background-tint-02 italic text-center"
              )}
            >
              <Text font="secondary-mono" color={lineTextColor(line.type)}>
                {content}
              </Text>
            </div>
          );
        })}
      </div>
      <div>
        {lines.map((line, idx) => {
          const isHeader = line.type === "header";
          const showAdded = line.type === "added";
          const content =
            line.type === "removed" ? BLANK : line.content || BLANK;
          return (
            <div
              key={`r-${idx}`}
              className={cn(
                "px-2 py-0.5 whitespace-pre-wrap wrap-break-word",
                showAdded && "bg-status-success-01",
                isHeader && "bg-background-tint-02 italic text-center"
              )}
            >
              <Text font="secondary-mono" color={lineTextColor(line.type)}>
                {content}
              </Text>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * DiffBody - Diff renderer for the edit/write tool.
 *
 * Replaces the old DiffView with design-token colors (no hardcoded hex) and
 * adds a unified <-> side-by-side toggle. Auto-picks side-by-side for hunks
 * larger than SIDE_BY_SIDE_AUTO_THRESHOLD.
 */
export default function DiffBody({ toolCall }: ToolCardBodyProps) {
  const oldContent = toolCall.oldContent ?? "";
  const newContent = toolCall.newContent ?? "";

  const diffLines = useMemo(() => {
    const rawDiff = computeDiff(oldContent, newContent);
    return collapseUnchanged(rawDiff);
  }, [oldContent, newContent]);

  const stats = useMemo(() => {
    const added = diffLines.filter((l) => l.type === "added").length;
    const removed = diffLines.filter((l) => l.type === "removed").length;
    return { added, removed };
  }, [diffLines]);

  const autoSideBySide =
    stats.added + stats.removed > SIDE_BY_SIDE_AUTO_THRESHOLD;
  const [mode, setMode] = useState<"unified" | "side-by-side">(
    autoSideBySide ? "side-by-side" : "unified"
  );

  if (!newContent && !oldContent) {
    return null;
  }

  return (
    <ToolCardSurface scroll={false}>
      <div
        className={cn(
          "px-2 py-0.5 border-b-[0.5px] border-border-01",
          "bg-background-tint-01 flex items-center gap-2"
        )}
      >
        {toolCall.description && (
          <span className="truncate flex-1 min-w-0">
            <Text font="secondary-mono" color="text-03" nowrap>
              {toolCall.description}
            </Text>
          </span>
        )}
        <div className="flex items-center gap-2 shrink-0">
          {stats.added > 0 && (
            <span className="text-status-success-05">
              <Text font="figure-small-value" color="inherit">
                {`+${stats.added}`}
              </Text>
            </span>
          )}
          {stats.removed > 0 && (
            <span className="text-status-error-05">
              <Text font="figure-small-value" color="inherit">
                {`-${stats.removed}`}
              </Text>
            </span>
          )}
          <Button
            variant="default"
            prominence="tertiary"
            size="2xs"
            icon={mode === "unified" ? SvgColumn : SvgMenu}
            onClick={() =>
              setMode(mode === "unified" ? "side-by-side" : "unified")
            }
            tooltip={
              mode === "unified"
                ? "Switch to side-by-side"
                : "Switch to unified"
            }
          />
        </div>
      </div>

      {mode === "unified" ? (
        <UnifiedDiff lines={diffLines} />
      ) : (
        <SideBySideDiff lines={diffLines} />
      )}
    </ToolCardSurface>
  );
}
