import { expect, test } from "@playwright/test";

test("SKILL.md populates the create editor after confirmation", async ({
  page,
}) => {
  await page.goto("/app/customize/skills/new");

  const editor = page.getByRole("textbox", { name: "SKILL.md", exact: true });
  await editor.fill(
    '---\nname: "typed-title"\ndescription: "Typed description"\n---\n\nTyped instructions'
  );

  await page.getByLabel("Add skill files").setInputFiles({
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

  const confirmation = page
    .getByRole("dialog")
    .filter({ hasText: "Import this skill?" });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Import skill" }).click();

  await expect(editor).toHaveValue(
    /^---\nname: "uploaded-skill"\ndescription: "Uploaded description"\n---\n\nUploaded instructions\s*$/
  );
});
