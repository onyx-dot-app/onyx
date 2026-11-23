import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";

export const PLUGIN_MANIFEST_PATHS: readonly string[] = [
  ".claude-plugin/plugin.json",
  ".codex-plugin/plugin.json",
  "plugin.json",
];

export async function zipHasPluginManifest(file: File): Promise<boolean> {
  const { BlobReader, ZipReader } = await import("@zip.js/zip.js");
  const reader = new ZipReader(new BlobReader(file));
  try {
    const entries = await reader.getEntries();
    return entries.some((entry) => {
      const path = entry.filename.replace(/^\.?\//, "");
      if (PLUGIN_MANIFEST_PATHS.includes(path)) return true;
      const slash = path.indexOf("/");
      return slash > 0 && PLUGIN_MANIFEST_PATHS.includes(path.slice(slash + 1));
    });
  } finally {
    await reader.close();
  }
}

export type PluginUploadKind = "plugin" | "skill";

export async function pluginUploadKind(
  bundle: PreparedSkillBundle
): Promise<PluginUploadKind> {
  if (bundle.source === "skill-md") return "skill";
  return (await zipHasPluginManifest(bundle.file)) ? "plugin" : "skill";
}
