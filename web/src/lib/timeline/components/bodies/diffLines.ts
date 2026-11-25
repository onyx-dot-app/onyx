export type DiffLineType = "added" | "removed" | "unchanged" | "header";

export interface DiffLine {
  type: DiffLineType;
  content: string;
  oldLineNum?: number;
  newLineNum?: number;
}

/** A text as lines; an empty text, and a final newline, add no line. */
function splitLines(text: string): string[] {
  if (text === "") return [];
  const lines = text.split("\n");
  if (lines[lines.length - 1] === "") lines.pop();
  return lines;
}

type DiffOp = "keep" | "remove" | "add";

/** Past this many edits in the middle of a diff, it falls back to a replace. */
const MAX_EDITS = 2000;

/**
 * The shortest edit script from `a` to `b` (Myers, O(ND)): cheap while few
 * lines change, whatever the file's length. `null` past `MAX_EDITS` edits.
 */
function editScript(a: string[], b: string[]): DiffOp[] | null {
  const n = a.length;
  const m = b.length;
  const max = Math.min(n + m, MAX_EDITS);
  const offset = max + 1;
  const v = new Int32Array(2 * max + 3);
  // trace[d] holds the furthest x per diagonal k before round d, for k in
  // [-d - 1, d + 1], at index k + d + 1.
  const trace: Int32Array[] = [];
  for (let d = 0; d <= max; d++) {
    trace.push(v.slice(offset - d - 1, offset + d + 2));
    for (let k = -d; k <= d; k += 2) {
      let x =
        k === -d || (k !== d && v[offset + k - 1]! < v[offset + k + 1]!)
          ? v[offset + k + 1]!
          : v[offset + k - 1]! + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) {
        x++;
        y++;
      }
      v[offset + k] = x;
      if (x >= n && y >= m) return backtrack(trace, d, n, m);
    }
  }
  return null;
}

function backtrack(
  trace: Int32Array[],
  edits: number,
  n: number,
  m: number
): DiffOp[] {
  const ops: DiffOp[] = [];
  let x = n;
  let y = m;
  for (let d = edits; d > 0; d--) {
    const before = trace[d]!;
    const k = x - y;
    const down =
      k === -d || (k !== d && before[k - 1 + d + 1]! < before[k + 1 + d + 1]!);
    const prevK = down ? k + 1 : k - 1;
    const prevX = before[prevK + d + 1]!;
    const prevY = prevX - prevK;
    while (x > prevX && y > prevY) {
      ops.push("keep");
      x--;
      y--;
    }
    ops.push(down ? "add" : "remove");
    x = prevX;
    y = prevY;
  }
  while (x > 0 && y > 0) {
    ops.push("keep");
    x--;
    y--;
  }
  return ops.reverse();
}

/** A line diff with the fewest changed lines, after the shared head and tail are cut off. */
export function computeDiff(oldText: string, newText: string): DiffLine[] {
  const oldLines = splitLines(oldText);
  const newLines = splitLines(newText);
  let head = 0;
  while (
    head < oldLines.length &&
    head < newLines.length &&
    oldLines[head] === newLines[head]
  ) {
    head++;
  }
  let tail = 0;
  while (
    tail < oldLines.length - head &&
    tail < newLines.length - head &&
    oldLines[oldLines.length - 1 - tail] ===
      newLines[newLines.length - 1 - tail]
  ) {
    tail++;
  }
  const oldMid = oldLines.slice(head, oldLines.length - tail);
  const newMid = newLines.slice(head, newLines.length - tail);
  const ops: DiffOp[] = editScript(oldMid, newMid) ?? [
    ...oldMid.map((): DiffOp => "remove"),
    ...newMid.map((): DiffOp => "add"),
  ];

  const result: DiffLine[] = [];
  let oldLineNum = 1;
  let newLineNum = 1;
  const push = (type: DiffLineType, content: string) => {
    if (type === "removed") {
      result.push({ type, content, oldLineNum: oldLineNum++ });
    } else if (type === "added") {
      result.push({ type, content, newLineNum: newLineNum++ });
    } else {
      result.push({
        type,
        content,
        oldLineNum: oldLineNum++,
        newLineNum: newLineNum++,
      });
    }
  };

  for (let i = 0; i < head; i++) push("unchanged", oldLines[i] ?? "");
  let i = 0;
  let j = 0;
  for (const op of ops) {
    if (op === "keep") {
      push("unchanged", oldMid[i] ?? "");
      i++;
      j++;
    } else if (op === "remove") {
      push("removed", oldMid[i] ?? "");
      i++;
    } else {
      push("added", newMid[j] ?? "");
      j++;
    }
  }
  for (let k = oldLines.length - tail; k < oldLines.length; k++) {
    push("unchanged", oldLines[k] ?? "");
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
  /** The shown lines, which the patch's line limit can cut. */
  lines: DiffLine[];
  /** Every added and removed line of the file, shown or not. */
  added: number;
  removed: number;
}

export interface ParsedPatch {
  /** The files that have a panel; later files wait behind the line limit. */
  files: PatchFile[];
  /** Every added and removed line of the patch. */
  added: number;
  removed: number;
  /** Lines that the limit left out, in the panels and in later files. */
  omittedLines: number;
}

/** The most patch lines shown; the rest is a count. Totals keep all lines. */
const MAX_PATCH_LINES = 2000;

/** A heredoc wrapper around a patch (`<<EOF` ... `EOF`), as the tool accepts. */
const HEREDOC_OPEN = /^<<['"]?(\w+)['"]?\s*$/;

/**
 * An apply_patch patch split by file. Its `@@` headers carry no line
 * offsets, so only a new file's lines are numbered. A hunk header with
 * context becomes a note; a bare `@@` is dropped. The totals are the one
 * count of the patch's changes.
 */
export function parseApplyPatch(patch: string): ParsedPatch {
  const parsed: ParsedPatch = {
    files: [],
    added: 0,
    removed: 0,
    omittedLines: 0,
  };
  let file: PatchFile | null = null;
  let isNewFile = false;
  let count = 0;
  let lines = patch.split(/\r?\n/);
  const opener = HEREDOC_OPEN.exec(lines[0]?.trim() ?? "");
  if (opener) {
    const closing = lines.findLastIndex((line) => line.trim() === opener[1]);
    lines = lines.slice(1, closing > 0 ? closing : undefined);
  }
  let shown = 0;
  for (const line of lines) {
    if (line === "*** Begin Patch" || line === "*** End Patch") continue;
    const header = line.match(/^\*\*\* (Add|Update|Delete) File: (.*)$/);
    if (header || (file === null && count === 0)) {
      count++;
      isNewFile = header?.[1] === "Add";
      file = null;
      if (shown < MAX_PATCH_LINES) {
        file = { path: header?.[2] ?? "", lines: [], added: 0, removed: 0 };
        parsed.files.push(file);
      }
      if (header) continue;
    }
    if (line.startsWith("*** Move to: ")) {
      if (file) file.path = `${file.path} \u2192 ${line.slice(13)}`;
      continue;
    }
    let next: DiffLine | null = null;
    if (line.startsWith("@@")) {
      const context = line.slice(2).trim();
      if (context) next = { type: "header", content: context };
    } else if (line.startsWith("+")) {
      parsed.added++;
      if (file) file.added++;
      next = {
        type: "added",
        content: line.slice(1),
        newLineNum: isNewFile && file ? file.added : undefined,
      };
    } else if (line.startsWith("-")) {
      parsed.removed++;
      if (file) file.removed++;
      next = { type: "removed", content: line.slice(1) };
    } else {
      next = {
        type: "unchanged",
        content: line.startsWith(" ") ? line.slice(1) : line,
      };
    }
    if (next === null) continue;
    if (shown >= MAX_PATCH_LINES || file === null) {
      parsed.omittedLines++;
    } else {
      shown++;
      file.lines.push(next);
    }
  }
  return parsed;
}
