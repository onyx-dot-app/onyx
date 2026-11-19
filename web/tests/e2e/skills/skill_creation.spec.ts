import { expect, test } from "@playwright/test";
import { SkillsLibraryPage } from "@tests/e2e/pages/SkillsLibraryPage";

test("SKILL.md populates the create editor after confirmation", async ({
  page,
}) => {
  const skills = new SkillsLibraryPage(page);
  await skills.openCreatePage();
  await skills.skillMdEditor.fill(
    '---\nname: "typed-title"\ndescription: "Typed description"\n---\n\nTyped instructions'
  );

  await skills.addSkillFiles({
    name: "SKILL.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "---\n" +
        "name: uploaded-skill\n" +
        "description: Uploaded description\n" +
        "---\n\n" +
        "Uploaded instructions\n"
    ),
  });
  await skills.confirmSkillImport();

  await expect(skills.skillMdEditor).toHaveValue(
    /^---\nname: "uploaded-skill"\ndescription: "Uploaded description"\n---\n\nUploaded instructions\s*$/
  );
});
