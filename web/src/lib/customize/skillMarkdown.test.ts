import {
  composeSkillMarkdown,
  parseSkillMarkdown,
} from "@/lib/customize/skillMarkdown";

test("the composed text reads back to the same fields", () => {
  const text = composeSkillMarkdown({
    name: "release-notes",
    description: 'Turns "merged" PRs into notes: one line each.',
    instructions: "# Release notes\n\nWrite the notes.",
  });
  expect(parseSkillMarkdown(text)).toEqual({
    ok: true,
    name: "release-notes",
    description: 'Turns "merged" PRs into notes: one line each.',
    instructions: "# Release notes\n\nWrite the notes.",
  });
});

test("plain and single-quoted values read as text", () => {
  expect(
    parseSkillMarkdown(
      "---\nname: hi\ndescription: 'it''s a test'\n---\n\nbody"
    )
  ).toEqual({
    ok: true,
    name: "hi",
    description: "it's a test",
    instructions: "body",
  });
});

test("text without a frontmatter or a description is refused", () => {
  expect(parseSkillMarkdown("just instructions")).toEqual({
    ok: false,
    error: "frontmatter",
  });
  expect(parseSkillMarkdown("---\nname: hi\n---\n\nbody")).toEqual({
    ok: false,
    error: "description",
  });
});

test("block descriptions read as text", () => {
  const literal = parseSkillMarkdown(
    "---\nname: hi\ndescription: |-\n  Line one.\n  Line two.\n---\nbody"
  );
  expect(literal.ok && literal.description).toBe("Line one.\nLine two.");
  const folded = parseSkillMarkdown(
    "---\nname: hi\ndescription: >\n  Summarize reports\n  for the week.\n---\nbody"
  );
  expect(folded.ok && folded.description).toBe(
    "Summarize reports for the week."
  );
});

test("the closing --- must be on its own line", () => {
  expect(
    parseSkillMarkdown("---\nname: hi\ndescription: d\n---Draft notes")
  ).toEqual({ ok: false, error: "frontmatter" });
});

test("the instructions keep their indentation", () => {
  const parsed = parseSkillMarkdown(
    "---\nname: hi\ndescription: d\n---\n\n    SELECT 1;\n"
  );
  expect(parsed.ok && parsed.instructions).toBe("    SELECT 1;");
});
