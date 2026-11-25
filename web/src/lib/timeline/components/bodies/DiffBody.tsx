"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, CodePanel, type CodePanelLine } from "@opal/components";
import { SvgColumn, SvgMenu } from "@opal/icons";
import { DiffStat } from "@/lib/timeline/components/bodies/DiffStat";
import {
  collapseUnchanged,
  computeDiff,
  countDiffLines,
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
  title: string;
  copyText?: string;
} & ({ oldText: string; newText: string } | { lines: DiffLine[] });

/**
 * A diff panel with +/- counts and a unified or side-by-side toggle. It
 * takes old and new text, or lines that are already diffed. It picks
 * side-by-side for changes larger than SIDE_BY_SIDE_AUTO_THRESHOLD.
 */
export function DiffBody(props: DiffBodyProps) {
  const t = useTranslations("craft.toolCards.diff");
  const { title, copyText } = props;
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
  const stats = useMemo(() => countDiffLines(diffLines), [diffLines]);

  const autoSideBySide =
    stats.added + stats.removed > SIDE_BY_SIDE_AUTO_THRESHOLD;
  const [mode, setMode] = useState<"unified" | "side-by-side">(
    autoSideBySide ? "side-by-side" : "unified"
  );

  if (given === null && !newText && !oldText) {
    return null;
  }

  return (
    <CodePanel>
      <CodePanel.Header
        title={title}
        copyText={copyText ?? newText}
        rightChildren={
          <>
            <DiffStat added={stats.added} removed={stats.removed} />
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
