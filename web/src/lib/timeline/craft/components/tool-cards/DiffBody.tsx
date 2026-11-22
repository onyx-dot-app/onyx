"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Badge, Button, CodePanel, type CodePanelLine } from "@opal/components";
import { SvgColumn, SvgMenu, SvgMinus, SvgPlus } from "@opal/icons";
import type { ToolCardBodyProps } from "@/lib/timeline/craft/components/tool-cards/interfaces";

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
  formatUnchanged: (count: number) => string,
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
      return [{ type: "header", content: formatUnchanged(lines.length) }];
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
      content: formatUnchanged(count),
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

/** A diff line as a `CodePanel` line, numbered on the side it belongs to. */
function toPanelLine(line: DiffLine): CodePanelLine {
  if (line.type === "header") return { kind: "note", content: line.content };
  return {
    kind:
      line.type === "added"
        ? "added"
        : line.type === "removed"
          ? "removed"
          : "context",
    number: line.newLineNum ?? line.oldLineNum,
    content: line.content,
  };
}

/** One side of a split diff: the other side's lines stay as blank rows. */
function toSideLine(line: DiffLine, side: "old" | "new"): CodePanelLine {
  if (line.type === "header") return { kind: "note", content: line.content };
  const otherSide = side === "old" ? "added" : "removed";
  if (line.type === otherSide) return { content: BLANK };
  return {
    kind: line.type === "unchanged" ? "context" : line.type,
    number: side === "old" ? line.oldLineNum : line.newLineNum,
    content: line.content,
  };
}

/**
 * DiffBody - Diff renderer for the edit/write tool.
 *
 * Replaces the old DiffView with design-token colors (no hardcoded hex) and
 * adds a unified <-> side-by-side toggle. Auto-picks side-by-side for hunks
 * larger than SIDE_BY_SIDE_AUTO_THRESHOLD.
 */
export default function DiffBody({ toolCall }: ToolCardBodyProps) {
  const t = useTranslations("craft.toolCards.diff");
  const oldContent = toolCall.oldContent ?? "";
  const newContent = toolCall.newContent ?? "";

  const diffLines = useMemo(() => {
    const rawDiff = computeDiff(oldContent, newContent);
    return collapseUnchanged(rawDiff, (count) =>
      t("unchangedLines.label", { count })
    );
  }, [oldContent, newContent, t]);

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
    <CodePanel>
      <CodePanel.Header
        title={toolCall.description || ""}
        copyText={newContent}
        rightChildren={
          <>
            {stats.added > 0 && (
              <Badge
                icon={SvgPlus}
                title={String(stats.added)}
                color="success"
              />
            )}
            {stats.removed > 0 && (
              <Badge
                icon={SvgMinus}
                title={String(stats.removed)}
                color="error"
              />
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
                  ? t("viewToggle.sideBySideTooltip")
                  : t("viewToggle.unifiedTooltip")
              }
            />
          </>
        }
      />
      {mode === "unified" ? (
        <CodePanel.Lines
          lineNumbers
          markers
          lines={diffLines.map(toPanelLine)}
        />
      ) : (
        <CodePanel.Columns>
          <CodePanel.Lines
            lineNumbers
            lines={diffLines.map((line) => toSideLine(line, "old"))}
          />
          <CodePanel.Lines
            lineNumbers
            lines={diffLines.map((line) => toSideLine(line, "new"))}
          />
        </CodePanel.Columns>
      )}
    </CodePanel>
  );
}
