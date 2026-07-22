import {
  discardSkillCreationDraft,
  getSkillCreationDraft,
  stageSkillCreationDraft,
  type SkillCreationDraft,
} from "@/lib/skills/creationDraft";

function draft(name: string): SkillCreationDraft {
  const file = new File([name], `${name}.zip`);
  return {
    contents: {
      name,
      description: `${name} description`,
      instructions_markdown: `${name} instructions`,
      files: [{ path: "SKILL.md", size: file.size }],
    },
    upload: {
      file,
      displayName: file.name,
      entries: [{ path: "SKILL.md", size: file.size }],
      containsSkillMd: true,
    },
  };
}

describe("skill creation draft", () => {
  it("retains only the current draft within a tab", () => {
    const firstDraft = draft("first");
    const secondDraft = draft("second");
    const firstId = stageSkillCreationDraft(firstDraft);
    const secondId = stageSkillCreationDraft(secondDraft);

    expect(getSkillCreationDraft(firstId)).toBeUndefined();
    expect(getSkillCreationDraft(secondId)).toBe(secondDraft);

    discardSkillCreationDraft(firstId);
    expect(getSkillCreationDraft(secondId)).toBe(secondDraft);

    discardSkillCreationDraft(secondId);
    expect(getSkillCreationDraft(secondId)).toBeUndefined();
  });
});
