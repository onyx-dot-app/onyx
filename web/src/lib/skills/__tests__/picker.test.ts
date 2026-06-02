import { detectSlashTrigger, filterPickerSkills } from "@/lib/skills/picker";
import type { PickerSkill } from "@/lib/skills/picker";

// detectSlashTrigger is the contract that the Craft skill picker + skill-tile
// insertion depend on: the `/<query>` token it reports drives how many
// characters get consumed when a tile is dropped. Pin the spec with hardcoded
// expectations (do not derive from the implementation).
describe("detectSlashTrigger", () => {
  it("returns null when there is no slash", () => {
    expect(detectSlashTrigger("")).toBeNull();
    expect(detectSlashTrigger("hello world")).toBeNull();
  });

  it("returns null for a slash that is not at start or after whitespace", () => {
    expect(detectSlashTrigger("a/b")).toBeNull();
    expect(detectSlashTrigger("http://x")).toBeNull();
    expect(detectSlashTrigger("/a b/c")).toBeNull();
  });

  it("returns null when the query contains whitespace", () => {
    expect(detectSlashTrigger("/foo bar")).toBeNull();
  });

  it("matches a bare slash at the start", () => {
    expect(detectSlashTrigger("/")).toEqual({ slashIndex: 0, query: "" });
  });

  it("matches a slash query at the start", () => {
    expect(detectSlashTrigger("/pp")).toEqual({ slashIndex: 0, query: "pp" });
  });

  it("matches a slash query after preceding text + whitespace", () => {
    expect(detectSlashTrigger("make me /pp")).toEqual({
      slashIndex: 8,
      query: "pp",
    });
  });

  it("uses the last eligible slash when several are present", () => {
    expect(detectSlashTrigger("/a /b")).toEqual({ slashIndex: 3, query: "b" });
  });
});

describe("filterPickerSkills", () => {
  const skills: PickerSkill[] = [
    { slug: "pptx", name: "Slides", description: "Make slide decks" },
    { slug: "pdf", name: "PDF", description: "Work with PDF files" },
  ];

  it("returns all skills for an empty query", () => {
    expect(filterPickerSkills(skills, "")).toEqual(skills);
  });

  it("matches against slug, name, and description (case-insensitive)", () => {
    expect(filterPickerSkills(skills, "PPT").map((s) => s.slug)).toEqual([
      "pptx",
    ]);
    expect(filterPickerSkills(skills, "slide").map((s) => s.slug)).toEqual([
      "pptx",
    ]);
    expect(filterPickerSkills(skills, "files").map((s) => s.slug)).toEqual([
      "pdf",
    ]);
  });

  it("returns nothing when no field matches", () => {
    expect(filterPickerSkills(skills, "zzz")).toEqual([]);
  });
});
