import {
  computeDiff,
  countDiffLines,
  formatDiffCount,
  parseApplyPatch,
} from "@/lib/timeline/components/bodies/diffLines";

const PATCH = [
  "*** Begin Patch",
  "*** Add File: new.py",
  "+one",
  "+two",
  "*** Update File: old.py",
  "*** Move to: moved.py",
  "@@ def f():",
  " keep",
  "-a = 1",
  "+a = 2",
  "+b = 3",
  "*** End Patch",
].join("\n");

test("a patch splits by file with counts and line types", () => {
  const { files, added, removed, omittedLines } = parseApplyPatch(PATCH);
  const [newFile, updated] = files;
  expect({ added, removed, omittedLines }).toEqual({
    added: 4,
    removed: 1,
    omittedLines: 0,
  });
  expect(newFile).toMatchObject({ path: "new.py", added: 2, removed: 0 });
  expect(newFile?.lines).toEqual([
    { type: "added", content: "one", newLineNum: 1 },
    { type: "added", content: "two", newLineNum: 2 },
  ]);
  expect(updated).toMatchObject({
    path: "old.py → moved.py",
    added: 2,
    removed: 1,
  });
  expect(updated?.lines.map((line) => line.type)).toEqual([
    "header",
    "unchanged",
    "removed",
    "added",
    "added",
  ]);
  expect(updated?.lines[0]?.content).toBe("def f():");
});

test("a heredoc wrapper and a bare @@ add no lines", () => {
  const { files } = parseApplyPatch(
    `<<'EOF'\n*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch\nEOF`
  );
  expect(files[0]?.lines.map((line) => line.type)).toEqual([
    "removed",
    "added",
  ]);
});

test("a long patch is cut, the panels stay bounded, and the totals keep every line", () => {
  const body = Array.from({ length: 2500 }, (_, i) => `+line ${i}`).join("\n");
  const patch = `*** Add File: big.txt\n${body}\n*** Add File: late.txt\n+x`;
  const parsed = parseApplyPatch(patch);
  expect(parsed.files).toHaveLength(1);
  expect(parsed.files[0]?.lines).toHaveLength(2000);
  expect(parsed.files[0]?.added).toBe(2500);
  expect(parsed.added).toBe(2501);
  expect(parsed.omittedLines).toBe(501);
});

test("a diff counts only the lines that changed", () => {
  // An inserted line that repeats later is still one addition.
  expect(
    countDiffLines(computeDiff("a\nb\nc\nb\n", "a\nb\nx\nc\nb\n"))
  ).toEqual({ added: 1, removed: 0 });
  expect(countDiffLines(computeDiff("a\nb\nc", "a\nc"))).toEqual({
    added: 0,
    removed: 1,
  });
});

test("a long file with two far apart edits counts exactly two and two", () => {
  const body = Array.from({ length: 2100 }, (_, i) => `line ${i}`);
  const edited = [...body];
  edited[0] = "first";
  edited[2099] = "last";
  expect(
    countDiffLines(computeDiff(body.join("\n"), edited.join("\n")))
  ).toEqual({ added: 2, removed: 2 });
});

test("a diff with scattered edits keeps every shared line", () => {
  const body = Array.from({ length: 300 }, (_, i) => `line ${i % 7}`);
  const edited = body.filter((_, i) => i % 10 !== 3);
  edited.splice(100, 0, "new a", "new b");
  const lines = computeDiff(body.join("\n"), edited.join("\n"));
  const kept = lines.filter((line) => line.type !== "added");
  expect(kept.map((line) => line.content)).toEqual(body);
  expect(
    lines.filter((line) => line.type !== "removed").map((l) => l.content)
  ).toEqual(edited);
});

test("an empty side and a missing final newline add no phantom changes", () => {
  expect(countDiffLines(computeDiff("", "a\nb"))).toEqual({
    added: 2,
    removed: 0,
  });
  expect(countDiffLines(computeDiff("a\nb", ""))).toEqual({
    added: 0,
    removed: 2,
  });
  const lines = computeDiff("a\nb", "a\nc");
  expect(
    lines.map((line) => [line.type, line.oldLineNum, line.newLineNum])
  ).toEqual([
    ["unchanged", 1, 1],
    ["removed", 2, undefined],
    ["added", undefined, 2],
  ]);
});

test("large counts are compact", () => {
  expect(formatDiffCount(999)).toBe("999");
  expect(formatDiffCount(1200)).toBe("1.2k");
  expect(formatDiffCount(25000)).toBe("25k");
});
