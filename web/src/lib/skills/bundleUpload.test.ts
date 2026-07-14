import {
  BlobReader,
  TextWriter,
  ZipReader,
  type FileEntry,
} from "@zip.js/zip.js";
import type { FileWithPath } from "react-dropzone";
import {
  getSkillDirectoryEntries,
  prepareSkillBundleUpload,
} from "./bundleUpload";

function fileAt(path: string, content: string): FileWithPath {
  const file = new File([content], path.split("/").at(-1)!, {
    type: "text/plain",
    lastModified: 1_700_000_000_000,
  }) as FileWithPath;
  Object.defineProperty(file, "path", { value: path });
  return file;
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

  it("strips one selected folder from entry paths", () => {
    const skillMd = fileAt("/example/SKILL.md", "instructions");
    const helper = fileAt("/example/scripts/helper.py", "print('hello')");

    const result = getSkillDirectoryEntries([helper, skillMd]);

    expect(result.directoryName).toBe("example");
    expect(result.entries.map((entry) => entry.path)).toEqual([
      "scripts/helper.py",
      "SKILL.md",
    ]);
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

  it("rejects a folder without top-level SKILL.md", () => {
    expect(() =>
      getSkillDirectoryEntries([
        fileAt("/example/nested/SKILL.md", "instructions"),
      ])
    ).toThrow("must contain SKILL.md at its top level");
  });

  it("rejects files from multiple roots", () => {
    expect(() =>
      getSkillDirectoryEntries([
        fileAt("/example/SKILL.md", "instructions"),
        fileAt("/other/helper.py", "print('hello')"),
      ])
    ).toThrow("one skill folder at a time");
  });

  it("ignores operating system metadata", () => {
    const result = getSkillDirectoryEntries([
      fileAt("/example/SKILL.md", "instructions"),
      fileAt("/example/.DS_Store", "metadata"),
      fileAt("/__MACOSX/example/._SKILL.md", "resource fork"),
    ]);

    expect(result.entries.map((entry) => entry.path)).toEqual(["SKILL.md"]);
  });
});
