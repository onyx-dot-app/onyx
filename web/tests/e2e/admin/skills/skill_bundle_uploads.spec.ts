import { randomBytes } from "crypto";
import { crc32 } from "zlib";

import { expect, test, type Page } from "@playwright/test";

interface ZipEntry {
  path: string;
  data: Buffer;
}

function storedZip(entries: ZipEntry[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.path);
    const crc = crc32(entry.data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(entry.data.length, 18);
    local.writeUInt32LE(entry.data.length, 22);
    local.writeUInt16LE(name.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(entry.data.length, 20);
    central.writeUInt32LE(entry.data.length, 24);
    central.writeUInt16LE(name.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, name, entry.data);
    centrals.push(central, name);
    offset += local.length + name.length + entry.data.length;
  }
  const centralDirectory = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralDirectory.length, 12);
  end.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, centralDirectory, end]);
}

function skillMd(name: string, instructions: string): Buffer {
  return Buffer.from(
    `---\nname: ${name}\ndescription: ${name} description\n---\n\n${instructions}\n`
  );
}

function zipFile(name: string, entries: ZipEntry[]) {
  return { name, mimeType: "application/zip", buffer: storedZip(entries) };
}

async function openUploadModal(page: Page) {
  await page.goto("/admin/skills");
  await page.getByRole("button", { name: "Create skill" }).click();
  await page.getByText("Upload a skill", { exact: true }).click();
  const dialog = page.getByRole("dialog").filter({ hasText: "Upload skill" });
  await expect(dialog).toBeVisible();
  return dialog;
}

async function deleteSkillsNamed(page: Page, names: string[]) {
  const response = await page.request.get("/api/skills");
  if (!response.ok()) return;
  const { customs } = (await response.json()) as {
    customs: { id: string; name: string }[];
  };
  for (const skill of customs) {
    if (names.includes(skill.name)) {
      await page.request.delete(`/api/skills/custom/${skill.id}`);
    }
  }
}

test.describe("Skill bundle uploads", () => {
  const suffix = Date.now().toString(36);
  const validName = `e2e-large-bundle-${suffix}`;
  const countName = `e2e-too-many-files-${suffix}`;
  const historyName = `e2e-history-${suffix}`;

  test.afterAll(async ({ browser }) => {
    const page = await browser.newPage({ storageState: "admin_auth.json" });
    await deleteSkillsNamed(page, [validName, countName, historyName]);
    await page.close();
  });

  test("batch upload imports a large bundle and reports each rejected bundle", async ({
    page,
  }) => {
    const dialog = await openUploadModal(page);

    const largeBundle = zipFile(`${validName}.zip`, [
      { path: "SKILL.md", data: skillMd(validName, "Read assets/blob.bin.") },
      // Random bytes keep the stored ZIP above the old 10 MiB proxy cap.
      { path: "assets/blob.bin", data: randomBytes(11 * 1024 * 1024) },
    ]);
    const tooManyFiles = zipFile(`${countName}.zip`, [
      { path: "SKILL.md", data: skillMd(countName, "Too many files.") },
      ...Array.from({ length: 500 }, (_, index) => ({
        path: `files/${index}.txt`,
        data: Buffer.from(`${index}`),
      })),
    ]);
    const notAZip = {
      name: "not-a-zip.zip",
      mimeType: "application/zip",
      buffer: Buffer.from("this is not a zip archive"),
    };
    const missingSkillMd = zipFile("missing-skill-md.zip", [
      { path: "README.md", data: Buffer.from("No skill here.") },
    ]);

    await dialog
      .locator('input[type="file"]')
      .setInputFiles([largeBundle, tooManyFiles, notAZip, missingSkillMd]);
    await expect(dialog.getByText("4 skill bundles selected")).toBeVisible();

    const uploadResponse = page.waitForResponse(
      (response) =>
        response.url().endsWith("/api/skills/custom/batch") &&
        response.request().method() === "POST"
    );
    await dialog.getByRole("button", { name: /Import/ }).click();
    expect((await uploadResponse).status()).toBe(200);

    await expect(dialog.getByText("1 skill imported. 3 failed.")).toBeVisible();
    await expect(dialog.getByText(validName, { exact: true })).toBeVisible();
    await expect(
      dialog.getByText(/bundle contains more than 500 files/)
    ).toBeVisible();
    await expect(dialog.getByText(/not-a-zip.*not a valid zip/i)).toBeVisible();
    await expect(dialog.getByText(/missing-skill-md.*SKILL\.md/)).toBeVisible();

    await dialog.getByRole("button", { name: "Done" }).click();
    await expect(page.getByText(validName).first()).toBeVisible();
    await expect(page.getByText(countName)).toHaveCount(0);
  });

  test("history lists each edit and restore brings back earlier instructions", async ({
    page,
  }) => {
    const created = await page.request.post("/api/skills/custom/editor", {
      multipart: {
        name: historyName,
        description: "History check",
        instructions_markdown: "Original instructions.",
      },
    });
    expect(created.status()).toBe(200);
    const { id } = (await created.json()) as { id: string };

    const patched = await page.request.patch(`/api/skills/custom/${id}`, {
      data: { instructions_markdown: "Edited instructions." },
    });
    expect(patched.status()).toBe(200);

    const unchanged = await page.request.patch(`/api/skills/custom/${id}`, {
      data: { instructions_markdown: "Edited instructions." },
    });
    expect(unchanged.status()).toBe(200);

    const history = await page.request.get(`/api/skills/custom/${id}/versions`);
    expect(history.status()).toBe(200);
    const versions = (await history.json()) as {
      id: string;
      version_number: number;
      is_current: boolean;
      has_bundle: boolean;
    }[];
    expect(versions.map((version) => version.version_number)).toEqual([2, 1]);
    expect(versions.map((version) => version.is_current)).toEqual([
      true,
      false,
    ]);
    const original = versions[1]!;

    const preview = await page.request.get(
      `/api/skills/custom/${id}/versions/${original.id}`
    );
    expect(preview.status()).toBe(200);
    expect(await preview.json()).toMatchObject({
      instructions_markdown: "Original instructions.",
    });

    const restored = await page.request.post(
      `/api/skills/custom/${id}/versions/${original.id}/restore`
    );
    expect(restored.status()).toBe(200);

    const afterRestore = await page.request.get(
      `/api/skills/custom/${id}/versions`
    );
    const restoredVersions = (await afterRestore.json()) as {
      version_number: number;
      is_current: boolean;
    }[];
    expect(restoredVersions[0]).toMatchObject({
      version_number: 3,
      is_current: true,
    });

    const current = await page.request.get(`/api/skills/${id}/preview`);
    expect(await current.json()).toMatchObject({
      instructions_markdown: "Original instructions.",
    });

    const missing = await page.request.get(
      `/api/skills/custom/${id}/versions/00000000-0000-4000-8000-000000000000`
    );
    expect(missing.status()).toBe(404);

    await page.goto("/admin/skills");
    await expect(page.getByText(historyName).first()).toBeVisible();
  });
});
