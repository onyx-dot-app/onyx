import { expect, test } from "@playwright/test";

test("SKILL.md populates the create form after confirmation", async ({
  page,
}) => {
  await page.goto("/craft/v1/skills/new");
  test.skip(
    !new URL(page.url()).pathname.startsWith("/craft/v1/skills/new"),
    "Onyx Craft is disabled in this environment"
  );

  const intro = page.getByRole("dialog").filter({ hasText: "Meet Craft" });
  const introAppeared = await intro
    .waitFor({ state: "visible", timeout: 3000 })
    .then(() => true)
    .catch(() => false);
  if (introAppeared) {
    await page.keyboard.press("Escape");
    await expect(intro).toBeHidden();
  }

  await page.locator('input[name="name"]').fill("Typed title");
  await page.locator('textarea[name="description"]').fill("Typed description");
  await page
    .locator('textarea[name="instructions_markdown"]')
    .fill("Typed instructions");

  await page.getByLabel("Import existing skill").setInputFiles({
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

  const confirmation = page
    .getByRole("dialog")
    .filter({ hasText: "Import this skill?" });
  await expect(confirmation).toBeVisible();
  await confirmation.getByRole("button", { name: "Import skill" }).click();

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
