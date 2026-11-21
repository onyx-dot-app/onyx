import { BlobWriter, TextReader, ZipWriter } from "@zip.js/zip.js";
import { pluginUploadKind } from "@/lib/plugins/upload";

async function zip(paths: string[]): Promise<File> {
  const writer = new ZipWriter(new BlobWriter("application/zip"), {
    useWebWorkers: false,
  });
  for (const path of paths) await writer.add(path, new TextReader("{}"));
  return new File([await writer.close()], "upload.zip");
}

test.each([
  [[".claude-plugin/plugin.json", "skills/a/SKILL.md"], "plugin"],
  [["kit/.codex-plugin/plugin.json", "kit/.mcp.json"], "plugin"],
  [["kit/plugin.json"], "plugin"],
  [["SKILL.md", "notes.md"], "skill"],
  [["kit/SKILL.md"], "skill"],
  [["a/b/.claude-plugin/plugin.json"], "skill"],
])("a zip with %j is a %s upload", async (paths, kind) => {
  const file = await zip(paths);
  expect(
    await pluginUploadKind({ file, displayName: file.name, source: "zip" })
  ).toBe(kind);
});

test("a SKILL.md upload is a skill", async () => {
  const file = new File(["---"], "SKILL.md");
  expect(
    await pluginUploadKind({
      file,
      displayName: "SKILL.md",
      source: "skill-md",
    })
  ).toBe("skill");
});
