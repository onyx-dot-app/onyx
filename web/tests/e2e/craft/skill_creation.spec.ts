import { expect, test } from "@playwright/test";

test("SKILL.md populates the create form after confirmation", async ({
  page,
}) => {
  await page.goto("/craft/v1/skills/new");

  await page.locator('input[name="name"]').fill("Typed title");
  await page.locator('textarea[name="description"]').fill("Typed description");
  await page
    .locator('textarea[name="instructions_markdown"]')
    .fill("Typed instructions");

  await page.locator('input[type="file"]').setInputFiles({
    name: "SKILL.md",
    mimeType: "text/markdown",
    buffer: Buffer.from(
      "---\n" +
        "name: Uploaded Skill\n" +
        "description: Uploaded description\n" +
        "---\n\n" +
        "Uploaded instructions\n"
    ),
  });

  await expect(page.getByText("Replace skill content?")).toBeVisible();
  await page.getByRole("button", { name: "Continue" }).click();

  await expect(page.locator('input[name="slug"]')).toHaveCount(0);
  await expect(page.locator('input[name="name"]')).toHaveValue(
    "Uploaded Skill"
  );
  await expect(page.locator('textarea[name="description"]')).toHaveValue(
    "Uploaded description"
  );
  await expect(
    page.locator('textarea[name="instructions_markdown"]')
  ).toHaveValue("Uploaded instructions");
});
