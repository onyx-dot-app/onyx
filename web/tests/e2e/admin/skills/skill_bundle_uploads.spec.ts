import { randomBytes } from "crypto";
import { crc32 } from "zlib";

import { expect, test, type Page } from "@playwright/test";
import * as yup from "yup";
import { AdminSkillsPage } from "@tests/e2e/pages/AdminSkillsPage";

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

async function deleteSkillsNamed(page: Page, names: string[]) {
  const response = await page.request.get("/api/skills");
  await expect(response, "List Skills for cleanup").toBeOK();
  const { customs } = yup
    .object({
      customs: yup
        .array(
          yup.object({
            id: yup.string().defined(),
            name: yup.string().defined(),
          })
        )
        .defined(),
    })
    .validateSync(await response.json(), { strict: true });
  for (const skill of customs) {
    if (names.includes(skill.name)) {
      const deleted = await page.request.delete(
        `/api/skills/custom/${skill.id}`
      );
      await expect(deleted, `Delete test Skill ${skill.name}`).toBeOK();
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
    try {
      await deleteSkillsNamed(page, [validName, countName, historyName]);
    } finally {
      await page.close();
    }
  });

  test("batch upload imports a large bundle and reports each rejected bundle", async ({
    page,
  }) => {
    const skills = new AdminSkillsPage(page);
    await skills.goto();
    const dialog = await skills.openUpload();

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

    await dialog.selectFiles([
      largeBundle,
      tooManyFiles,
      notAZip,
      missingSkillMd,
    ]);
    await dialog.expectMessage("4 skill bundles selected");
    await dialog.import();
    await dialog.expectMessage("1 skill imported. 3 failed.");
    await dialog.expectMessage(validName);
    await dialog.expectMessage(/bundle contains more than 500 files/);
    await dialog.expectMessage(/not-a-zip.*not a valid zip/i);
    await dialog.expectMessage(/missing-skill-md.*SKILL\.md/);
    await dialog.done();
    await skills.expectSkillVisible(validName);
    await skills.expectSkillAbsent(countName);
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
    const { id } = yup
      .object({ id: yup.string().defined() })
      .validateSync(await created.json(), { strict: true });

    const patched = await page.request.patch(`/api/skills/custom/${id}`, {
      data: { instructions_markdown: "Edited instructions." },
    });
    expect(patched.status()).toBe(200);

    const repeated = await page.request.patch(`/api/skills/custom/${id}`, {
      data: { instructions_markdown: "Edited instructions." },
    });
    expect(repeated.status()).toBe(200);

    const history = await page.request.get(`/api/skills/custom/${id}/versions`);
    expect(history.status()).toBe(200);
    const versions = yup
      .array(
        yup.object({
          id: yup.string().defined(),
          version_number: yup.number().defined(),
          is_current: yup.boolean().defined(),
          has_bundle: yup.boolean().defined(),
        })
      )
      .defined()
      .validateSync(await history.json(), { strict: true });
    expect(versions.map((version) => version.version_number)).toEqual([
      3, 2, 1,
    ]);
    expect(versions.map((version) => version.is_current)).toEqual([
      true,
      false,
      false,
    ]);
    const original = versions[2];
    if (!original) throw new Error("Original Skill version was not returned");

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
    await expect(afterRestore).toBeOK();
    const restoredVersions = yup
      .array(
        yup.object({
          version_number: yup.number().defined(),
          is_current: yup.boolean().defined(),
        })
      )
      .defined()
      .validateSync(await afterRestore.json(), { strict: true });
    expect(restoredVersions[0]).toMatchObject({
      version_number: 4,
      is_current: true,
    });

    const current = await page.request.get(`/api/skills/${id}/preview`);
    await expect(current).toBeOK();
    expect(await current.json()).toMatchObject({
      instructions_markdown: "Original instructions.",
    });

    const missing = await page.request.get(
      `/api/skills/custom/${id}/versions/00000000-0000-4000-8000-000000000000`
    );
    expect(missing.status()).toBe(404);

    const skills = new AdminSkillsPage(page);
    await skills.goto();
    await skills.expectSkillVisible(historyName);
  });
});
