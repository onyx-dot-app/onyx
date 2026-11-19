import { TextReader, Uint8ArrayWriter, ZipWriter } from "@zip.js/zip.js";

/** A file for `setInputFiles`. */
export interface UploadFile {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

/** A zip with the given files, built at run time. */
export async function zipFile(
  name: string,
  files: Record<string, string>
): Promise<UploadFile> {
  const writer = new ZipWriter(new Uint8ArrayWriter(), {
    useWebWorkers: false,
  });
  for (const [path, content] of Object.entries(files))
    await writer.add(path, new TextReader(content));
  return {
    name,
    mimeType: "application/zip",
    buffer: Buffer.from(await writer.close()),
  };
}

export function skillMd(name: string, description: string): string {
  return `---\nname: ${name}\ndescription: ${description}\n---\n\nDo the task.\n`;
}

export interface PluginZipOptions {
  name: string;
  version?: string;
  skills: string[];
  /** Server key to its .mcp.json entry. */
  mcpServers?: Record<string, Record<string, string>>;
  /** Extra files, such as a commands/ folder Onyx does not use. */
  extra?: Record<string, string>;
}

/** A Claude Code plugin zip: .claude-plugin/plugin.json, skills and an
 * optional .mcp.json. */
export async function pluginZip(
  options: PluginZipOptions
): Promise<UploadFile> {
  const files: Record<string, string> = {
    ".claude-plugin/plugin.json": JSON.stringify({
      name: options.name,
      version: options.version ?? "1.0.0",
      description: `E2E plugin ${options.name}`,
    }),
    ...options.extra,
  };
  for (const skill of options.skills)
    files[`skills/${skill}/SKILL.md`] = skillMd(skill, `E2E skill ${skill}`);
  if (options.mcpServers)
    files[".mcp.json"] = JSON.stringify({ mcpServers: options.mcpServers });
  return zipFile(`${options.name}.zip`, files);
}
