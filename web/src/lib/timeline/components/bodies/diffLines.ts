export type DiffLineType = "added" | "removed" | "unchanged" | "header";

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLineNum?: number;
  newLineNum?: number;
}

export function computeDiff(oldText: string, newText: string): DiffLine[] {
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

export function collapseUnchanged(
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

export interface DiffCounts {
  added: number;
  removed: number;
}

export function countDiffLines(lines: DiffLine[]): DiffCounts {
  let added = 0;
  let removed = 0;
  for (const line of lines) {
    if (line.type === "added") added++;
    else if (line.type === "removed") removed++;
  }
  return { added, removed };
}

// Adapted from T3 Code's formatCompactDiffCount.
export function formatDiffCount(value: number): string {
  if (value < 1000) return String(value);
  if (value < 999_500) {
    const k = value / 1000;
    return `${k < 10 ? k.toFixed(1).replace(/\.0$/, "") : Math.round(k)}k`;
  }
  const m = value / 1_000_000;
  return `${m < 10 ? m.toFixed(1).replace(/\.0$/, "") : Math.round(m)}m`;
}

export interface PatchFile {
  /** The file's path, and its new path when it moved. */
  path: string;
  lines: DiffLine[];
  added: number;
  removed: number;
}

/** The most patch lines shown; the rest is a note. Counts keep all lines. */
const MAX_PATCH_LINES = 2000;

/** A heredoc wrapper around a patch (`<<EOF` ... `EOF`), as the tool accepts. */
const HEREDOC_OPEN = /^<<['"]?(\w+)['"]?\s*$/;

/**
 * An apply_patch patch split by file. Its `@@` headers carry no line
 * offsets, so only a new file's lines are numbered. A hunk header with
 * context becomes a note; a bare `@@` is dropped.
 */
export function parseApplyPatch(
  patch: string,
  moreLines: (count: number) => string
): PatchFile[] {
  const files: PatchFile[] = [];
  let file: PatchFile | null = null;
  let isNewFile = false;
  let lines = patch.split(/\r?\n/);
  const opener = HEREDOC_OPEN.exec(lines[0]?.trim() ?? "");
  if (opener) {
    const closing = lines.findLastIndex((line) => line.trim() === opener[1]);
    lines = lines.slice(1, closing > 0 ? closing : undefined);
  }
  let shown = 0;
  let noted = false;
  for (const line of lines) {
    if (line === "*** Begin Patch" || line === "*** End Patch") continue;
    const header = line.match(/^\*\*\* (Add|Update|Delete) File: (.*)$/);
    if (header || file === null) {
      file = { path: header?.[2] ?? "", lines: [], added: 0, removed: 0 };
      isNewFile = header?.[1] === "Add";
      files.push(file);
      if (header) continue;
    }
    if (line.startsWith("*** Move to: ")) {
      file.path = `${file.path} → ${line.slice(13)}`;
      continue;
    }
    let next: DiffLine | null = null;
    if (line.startsWith("@@")) {
      const context = line.slice(2).trim();
      if (context) next = { type: "header", content: context };
    } else if (line.startsWith("+")) {
      file.added++;
      next = {
        type: "added",
        content: line.slice(1),
        newLineNum: isNewFile ? file.added : undefined,
      };
    } else if (line.startsWith("-")) {
      file.removed++;
      next = { type: "removed", content: line.slice(1) };
    } else {
      next = {
        type: "unchanged",
        content: line.startsWith(" ") ? line.slice(1) : line,
      };
    }
    if (next === null) continue;
    if (shown >= MAX_PATCH_LINES) {
      if (!noted) {
        file.lines.push({
          type: "header",
          content: moreLines(lines.length - shown),
        });
        noted = true;
      }
      continue;
    }
    shown++;
    file.lines.push(next);
  }
  return files;
}
