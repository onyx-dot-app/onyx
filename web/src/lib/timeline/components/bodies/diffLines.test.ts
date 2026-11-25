import {
  formatDiffCount,
  parseApplyPatch,
} from "@/lib/timeline/components/bodies/diffLines";

const more = (count: number) => `${count} more`;

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
  const [added, updated] = parseApplyPatch(PATCH, more);
  expect(added).toMatchObject({ path: "new.py", added: 2, removed: 0 });
  expect(added?.lines).toEqual([
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
  const [file] = parseApplyPatch(
    `<<'EOF'\n*** Begin Patch\n*** Update File: a.py\n@@\n-x\n+y\n*** End Patch\nEOF`,
    more
  );
  expect(file?.lines.map((line) => line.type)).toEqual(["removed", "added"]);
});

test("a long patch is cut with a note, and the counts keep every line", () => {
  const body = Array.from({ length: 2500 }, (_, i) => `+line ${i}`).join("\n");
  const [file] = parseApplyPatch(`*** Add File: big.txt\n${body}`, more);
  expect(file?.added).toBe(2500);
  expect(file?.lines).toHaveLength(2001);
  expect(file?.lines.at(-1)).toEqual({
    type: "header",
    content: expect.stringMatching(/ more$/),
  });
});

test("large counts are compact", () => {
  expect(formatDiffCount(999)).toBe("999");
  expect(formatDiffCount(1200)).toBe("1.2k");
  expect(formatDiffCount(25000)).toBe("25k");
});
