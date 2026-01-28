"use client";

import { useMemo } from "react";
import { cn } from "@/lib/utils";

interface DiffViewProps {
  oldContent: string;
  newContent: string;
  maxHeight?: string;
  /** File path for context (displayed in header) */
  filePath?: string;
}

interface DiffLine {
  type: "added" | "removed" | "unchanged" | "header";
  content: string;
  oldLineNum?: number;
  newLineNum?: number;
}

/**
 * Compute a simple line-by-line diff between old and new content.
 * Uses a basic LCS-like approach for reasonable diff output.
 */
function computeDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = oldText.split("\n");
  const newLines = newText.split("\n");

  const result: DiffLine[] = [];

  let oldIdx = 0;
  let newIdx = 0;
  let oldLineNum = 1;
  let newLineNum = 1;

  while (oldIdx < oldLines.length || newIdx < newLines.length) {
    const oldLine: string | undefined = oldLines[oldIdx];
    const newLine: string | undefined = newLines[newIdx];

    if (oldIdx >= oldLines.length || oldLine === undefined) {
      // All remaining new lines are additions
      result.push({
        type: "added",
        content: newLine ?? "",
        newLineNum: newLineNum++,
      });
      newIdx++;
    } else if (newIdx >= newLines.length || newLine === undefined) {
      // All remaining old lines are deletions
      result.push({
        type: "removed",
        content: oldLine,
        oldLineNum: oldLineNum++,
      });
      oldIdx++;
    } else if (oldLine === newLine) {
      // Lines match - unchanged
      result.push({
        type: "unchanged",
        content: oldLine,
        oldLineNum: oldLineNum++,
        newLineNum: newLineNum++,
      });
      oldIdx++;
      newIdx++;
    } else {
      // Lines differ - check if old line exists later in new, or vice versa
      const oldExistsLaterInNew = newLines.slice(newIdx + 1).includes(oldLine);
      const newExistsLaterInOld = oldLines.slice(oldIdx + 1).includes(newLine);

      if (!oldExistsLaterInNew && newExistsLaterInOld) {
        // Old line was removed
        result.push({
          type: "removed",
          content: oldLine,
          oldLineNum: oldLineNum++,
        });
        oldIdx++;
      } else if (oldExistsLaterInNew && !newExistsLaterInOld) {
        // New line was added
        result.push({
          type: "added",
          content: newLine,
          newLineNum: newLineNum++,
        });
        newIdx++;
      } else {
        // Both differ - show as removal then addition (replacement)
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

/**
 * Collapse unchanged lines in the middle of the diff.
 * Shows context lines around changes.
 */
function collapseUnchanged(
  lines: DiffLine[],
  contextLines: number = 3
): DiffLine[] {
  const result: DiffLine[] = [];
  const changeIndices: number[] = [];

  // Find all indices with changes
  lines.forEach((line, idx) => {
    if (line.type === "added" || line.type === "removed") {
      changeIndices.push(idx);
    }
  });

  if (changeIndices.length === 0) {
    // No changes, show a summary
    if (lines.length > 10) {
      return [{ type: "header", content: `(${lines.length} unchanged lines)` }];
    }
    return lines;
  }

  // Create a set of indices to show
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

  let lastShownIdx = -1;
  lines.forEach((line, idx) => {
    if (showIndices.has(idx)) {
      if (lastShownIdx !== -1 && idx - lastShownIdx > 1) {
        // Add collapse marker
        const skipped = idx - lastShownIdx - 1;
        result.push({
          type: "header",
          content: `... ${skipped} unchanged line${skipped > 1 ? "s" : ""} ...`,
        });
      }
      result.push(line);
      lastShownIdx = idx;
    }
  });

  return result;
}

/**
 * DiffView - Displays a diff between old and new content
 *
 * Shows added lines in green with + prefix
 * Shows removed lines in red with - prefix
 * Collapses long unchanged sections
 */
export default function DiffView({
  oldContent,
  newContent,
  maxHeight = "300px",
  filePath,
}: DiffViewProps) {
  const diffLines = useMemo(() => {
    const rawDiff = computeDiff(oldContent, newContent);
    return collapseUnchanged(rawDiff);
  }, [oldContent, newContent]);

  // Count changes for summary
  const stats = useMemo(() => {
    const added = diffLines.filter((l) => l.type === "added").length;
    const removed = diffLines.filter((l) => l.type === "removed").length;
    return { added, removed };
  }, [diffLines]);

  return (
    <div
      className={cn(
        "rounded-08 border overflow-hidden",
        "bg-[#fafafa] border-[#e5e5e5] dark:bg-[#151617] dark:border-[#2a2a2a]"
      )}
    >
      {/* Header with stats */}
      <div
        className={cn(
          "px-3 py-2 border-b text-xs flex items-center gap-3",
          "bg-[#f5f5f5] border-[#e5e5e5] dark:bg-[#1a1a1a] dark:border-[#2a2a2a]"
        )}
        style={{ fontFamily: "var(--font-dm-mono)" }}
      >
        {filePath && (
          <span className="text-text-03 truncate flex-1">{filePath}</span>
        )}
        <div className="flex items-center gap-2 shrink-0">
          {stats.added > 0 && (
            <span className="text-green-600 dark:text-green-400">
              +{stats.added}
            </span>
          )}
          {stats.removed > 0 && (
            <span className="text-red-600 dark:text-red-400">
              -{stats.removed}
            </span>
          )}
        </div>
      </div>

      {/* Diff content */}
      <div
        className="overflow-auto text-xs"
        style={{
          fontFamily: "var(--font-dm-mono)",
          maxHeight,
        }}
      >
        {diffLines.map((line, idx) => (
          <div
            key={idx}
            className={cn(
              "px-3 py-0.5 whitespace-pre-wrap break-words",
              line.type === "added" &&
                "bg-green-100 dark:bg-green-950/40 text-green-800 dark:text-green-300",
              line.type === "removed" &&
                "bg-red-100 dark:bg-red-950/40 text-red-800 dark:text-red-300",
              line.type === "unchanged" && "text-text-03",
              line.type === "header" &&
                "text-text-04 bg-[#f0f0f0] dark:bg-[#1d1d1d] text-center italic py-1"
            )}
          >
            {line.type === "added" && (
              <span className="select-none text-green-600 dark:text-green-500 mr-2">
                +
              </span>
            )}
            {line.type === "removed" && (
              <span className="select-none text-red-600 dark:text-red-500 mr-2">
                -
              </span>
            )}
            {line.type === "unchanged" && (
              <span className="select-none text-text-04 mr-2">&nbsp;</span>
            )}
            {line.content || (line.type !== "header" ? " " : "")}
          </div>
        ))}
      </div>
    </div>
  );
}
