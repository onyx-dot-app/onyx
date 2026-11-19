import { expect, test } from "@playwright/test";

test("SKILL.md populates the create form after confirmation", async ({
  page,
}) => {
  await page.goto("/app/customize/skills/new");

  await page.locator('input[name="name"]').fill("Typed title");
  await page.locator('textarea[name="description"]').fill("Typed description");
  await page
    .locator('textarea[name="instructions_markdown"]')
    .fill("Typed instructions");

  await page.getByLabel("Add supporting files").setInputFiles({
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

  await expect(page.locator('input[name="slug"]')).toHaveCount(0);
  await expect(page.locator('input[name="name"]')).toHaveValue(
    "uploaded-skill"
  );
  await expect(page.locator('textarea[name="description"]')).toHaveValue(
    "Uploaded description"
  );
  await expect(
    page.locator('textarea[name="instructions_markdown"]')
  ).toHaveValue("Uploaded instructions");
});
