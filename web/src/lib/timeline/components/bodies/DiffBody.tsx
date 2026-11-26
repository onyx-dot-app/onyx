"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, CodePanel, type CodePanelLine } from "@opal/components";
import { SvgColumn, SvgMenu } from "@opal/icons";
import type { RichStr } from "@opal/types";
import { DiffStat } from "@/lib/timeline/components/bodies/DiffStat";
import {
  collapseUnchanged,
  computeDiff,
  countDiffLines,
  type DiffCounts,
  type DiffLine,
} from "@/lib/timeline/components/bodies/diffLines";

const SIDE_BY_SIDE_AUTO_THRESHOLD = 20;
const BLANK = " ";

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

type DiffBodyProps = {
  title: string | RichStr;
  /** Defaults to the new text; a panel of ready lines has none. */
  copyText?: string;
  /** The change's line counts when `lines` is a cut of it. */
  counts?: DiffCounts;
} & ({ oldText: string; newText: string } | { lines: DiffLine[] });

/**
 * A diff panel with +/- counts and a unified or side-by-side toggle. It
 * takes old and new text, or lines that are already diffed. It picks
 * side-by-side for changes larger than SIDE_BY_SIDE_AUTO_THRESHOLD.
 */
export function DiffBody(props: DiffBodyProps) {
  const t = useTranslations("craft.toolCards.diff");
  const { title, copyText, counts } = props;
  const given = "lines" in props ? props.lines : null;
  const oldText = "oldText" in props ? props.oldText : "";
  const newText = "newText" in props ? props.newText : "";

  const diffLines = useMemo(
    () =>
      given ??
      collapseUnchanged(computeDiff(oldText, newText), (count) =>
        t("unchangedLines.label", { count })
      ),
    [given, oldText, newText, t]
  );
  const stats = useMemo(
    () => counts ?? countDiffLines(diffLines),
    [counts, diffLines]
  );

  // A pure addition or removal leaves one column empty: it stays unified.
  const autoSideBySide =
    stats.added > 0 &&
    stats.removed > 0 &&
    stats.added + stats.removed > SIDE_BY_SIDE_AUTO_THRESHOLD;
  const [mode, setMode] = useState<"unified" | "side-by-side">(
    autoSideBySide ? "side-by-side" : "unified"
  );

  const toggleLabel =
    mode === "unified"
      ? t("viewToggle.sideBySideTooltip")
      : t("viewToggle.unifiedTooltip");

  if (given === null && !newText && !oldText) {
    return null;
  }

  return (
    <CodePanel>
      <CodePanel.Header
        title={title}
        copyText={copyText ?? (given === null ? newText : undefined)}
        rightChildren={
          <>
            <DiffStat added={stats.added} removed={stats.removed} />
            {stats.added + stats.removed > 0 && (
              <Button
                variant="default"
                prominence="tertiary"
                size="2xs"
                icon={mode === "unified" ? SvgColumn : SvgMenu}
                onClick={() =>
                  setMode(mode === "unified" ? "side-by-side" : "unified")
                }
                tooltip={toggleLabel}
                aria-label={toggleLabel}
              />
            )}
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
          {/* Each side is its own table, so lines do not wrap: a wrapped
              line would push its side's rows out of line with the other. */}
          <CodePanel.Lines
            lineNumbers
            wrap={false}
            lines={diffLines.map((line) => toSideLine(line, "old"))}
          />
          <CodePanel.Lines
            lineNumbers
            wrap={false}
            lines={diffLines.map((line) => toSideLine(line, "new"))}
          />
        </CodePanel.Columns>
      )}
    </CodePanel>
  );
}
