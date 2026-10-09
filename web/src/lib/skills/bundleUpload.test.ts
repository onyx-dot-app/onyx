import {
  BlobReader,
  BlobWriter,
  TextReader,
  TextWriter,
  ZipReader,
  ZipWriter,
  type FileEntry,
} from "@zip.js/zip.js";
import type { FileWithPath } from "react-dropzone";
import {
  prepareSkillBundleUpload,
  prepareSkillFilesUpload,
} from "./bundleUpload";

function fileAt(path: string, content: string): FileWithPath {
  const file = new File([content], path.split("/").at(-1)!, {
    type: "text/plain",
    lastModified: 1_700_000_000_000,
  }) as FileWithPath;
  Object.defineProperty(file, "path", { value: path });
  return file;
}

async function zipFile(entries: Record<string, string>): Promise<FileWithPath> {
  const writer = new ZipWriter(new BlobWriter("application/zip"));
  for (const [path, content] of Object.entries(entries)) {
    await writer.add(path, new TextReader(content));
  }
  const blob = await writer.close();
  return new File([blob], "files.zip", {
    type: "application/zip",
  }) as FileWithPath;
}

describe("skill bundle upload preparation", () => {
  it("passes through one ZIP file", async () => {
    const zip = fileAt("./example.zip", "zip bytes");

    const prepared = await prepareSkillBundleUpload([zip]);

    expect(prepared).toEqual({
      file: zip,
      displayName: "example.zip",
      source: "zip",
    });
  });

  it("passes through a standalone SKILL.md", async () => {
    const skillMd = fileAt("./SKILL.md", "instructions");

    const prepared = await prepareSkillBundleUpload([skillMd]);

    expect(prepared).toEqual({
      file: skillMd,
      displayName: "SKILL.md",
      source: "skill-md",
    });
  });

  it("packages a dropped folder as a canonical ZIP", async () => {
    const prepared = await prepareSkillBundleUpload([
      fileAt("/example/SKILL.md", "instructions"),
      fileAt("/example/scripts/helper.py", "print('hello')"),
    ]);

    expect(prepared.source).toBe("folder");
    expect(prepared.file.name).toBe("example.zip");

    const reader = new ZipReader(new BlobReader(prepared.file));
    const entries = await reader.getEntries();
    expect(entries.map((entry) => entry.filename)).toEqual([
      "scripts/helper.py",
      "SKILL.md",
    ]);
    const skillMd = entries.find(
      (entry): entry is FileEntry =>
        entry.filename === "SKILL.md" && !entry.directory
    );
    expect(await skillMd!.getData(new TextWriter())).toBe("instructions");
    await reader.close();
  });

  it("rejects a folder without top-level SKILL.md", async () => {
    await expect(
      prepareSkillBundleUpload([
        fileAt("/example/nested/SKILL.md", "instructions"),
      ])
    ).rejects.toThrow("must contain SKILL.md at its top level");
  });

  it("rejects files from multiple roots", async () => {
    await expect(
      prepareSkillBundleUpload([
        fileAt("/example/SKILL.md", "instructions"),
        fileAt("/other/helper.py", "print('hello')"),
      ])
    ).rejects.toThrow("one ZIP, SKILL.md, or skill folder at a time");
  });

  it("ignores operating system metadata", async () => {
    const prepared = await prepareSkillBundleUpload([
      fileAt("/example/SKILL.md", "instructions"),
      fileAt("/example/.DS_Store", "metadata"),
      fileAt("/__MACOSX/example/._SKILL.md", "resource fork"),
    ]);

    const reader = new ZipReader(new BlobReader(prepared.file));
    const entries = await reader.getEntries();
    expect(entries.map((entry) => entry.filename)).toEqual(["SKILL.md"]);
    await reader.close();
  });
});

describe("skill file upload preparation", () => {
  it("passes through a single file", async () => {
    const file = fileAt("./notes.md", "notes");

    await expect(prepareSkillFilesUpload([file])).resolves.toEqual({
      file,
      displayName: "notes.md",
      entries: [{ path: "notes.md", size: 5 }],
      containsSkillMd: false,
    });
  });

  it("detects SKILL.md inside a ZIP before upload", async () => {
    const file = await zipFile({
      "bundle/SKILL.md": "instructions",
      "bundle/reference.md": "reference",
    });

    const prepared = await prepareSkillFilesUpload([file]);

    expect(prepared).toMatchObject({
      file,
      displayName: "files.zip",
      entries: null,
      containsSkillMd: true,
    });
  });

  it("preserves a dropped folder in the generated ZIP", async () => {
    const prepared = await prepareSkillFilesUpload([
      fileAt("/scripts/run.py", "print('hello')"),
      fileAt("/scripts/lib/util.py", "pass"),
    ]);

    const reader = new ZipReader(new BlobReader(prepared.file));
    const entries = await reader.getEntries();
    expect(entries.map((entry) => entry.filename)).toEqual([
      "scripts/run.py",
      "scripts/lib/util.py",
    ]);
    expect(prepared.containsSkillMd).toBe(false);
    await reader.close();
  });

  it("rejects a ZIP mixed with other selected files", async () => {
    await expect(
      prepareSkillFilesUpload([
        fileAt("./files.zip", "zip"),
        fileAt("./notes.md", "notes"),
      ])
    ).rejects.toThrow("Upload ZIP files separately");
  });
});
