import { mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { z } from "zod";
import type { SimpleStreamOptions } from "@earendil-works/pi-ai";
import type { Start } from "./protocol";

/** Pi's Vertex adapter accepts ADC files. Scope imported JSON credentials to this run. */
export async function prepareCredentials(
  start: Start,
  options: SimpleStreamOptions,
): Promise<() => Promise<void>> {
  const credentials = start.options.vertex_credentials;
  if (typeof credentials !== "string") return async () => {};
  const parsed = z
    .object({ type: z.string(), project_id: z.string().optional() })
    .passthrough()
    .parse(JSON.parse(credentials));
  const directory = await mkdtemp(join(tmpdir(), "onyx-agent-"));
  const filename = join(directory, "credentials.json");
  try {
    await writeFile(filename, JSON.stringify(parsed), { mode: 0o600 });
    options.env = { ...options.env, GOOGLE_APPLICATION_CREDENTIALS: filename };
    if (parsed.project_id && !options.env.GOOGLE_CLOUD_PROJECT)
      options.env.GOOGLE_CLOUD_PROJECT = parsed.project_id;
  } catch (error) {
    await rm(directory, { recursive: true, force: true });
    throw error;
  }
  return () => rm(directory, { recursive: true, force: true });
}
