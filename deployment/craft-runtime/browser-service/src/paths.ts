import * as NodeFSP from "node:fs/promises";
import * as NodePath from "node:path";
import { OperationError } from "./errors.ts";

export const CHAT_ID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

const LOOPBACK = /^(?:localhost|127\.\d+\.\d+\.\d+|\[::1\]|0\.0\.0\.0)(?:[:/?#]|$)/i;

/** Adds a scheme to bare hosts and allows only http, https and about:blank. */
export const normalizeUrl = (raw: string): string => {
  const trimmed = raw.trim();
  if (trimmed.length === 0) throw new OperationError("invalid_argument", "The URL is empty.");
  if (trimmed === "about:blank") return trimmed;
  // host:port is a bare host; any other leading "name:" is a scheme, which must be http(s).
  const hasScheme = !/^[^\s:/?#]+:\d+(?:[/?#]|$)/.test(trimmed) && /^[a-z][a-z\d+.-]*:/i.test(trimmed);
  const candidate = hasScheme ? trimmed : `${LOOPBACK.test(trimmed) ? "http" : "https"}://${trimmed}`;
  let parsed: URL;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new OperationError("invalid_argument", `Not a valid URL: ${trimmed.slice(0, 200)}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:")
    throw new OperationError("invalid_argument", "Only http and https URLs can be opened.");
  return parsed.href;
};

export const chatDir = (root: string, chat: string) => NodePath.resolve(root, chat);

/** Resolves a path relative to the chat session dir and rejects paths that leave it. */
export const resolveInChat = (root: string, chat: string, relative: string): string => {
  if (relative.length === 0 || relative.includes("\0"))
    throw new OperationError("invalid_argument", "The path is empty or not valid.");
  const base = chatDir(root, chat);
  const full = NodePath.resolve(base, relative);
  if (!full.startsWith(base + NodePath.sep))
    throw new OperationError(
      "invalid_argument",
      `The path ${relative.slice(0, 200)} is outside the chat session directory.`,
    );
  return full;
};

// File names are limited to 255 bytes; this leaves room for a " (n)" suffix.
const MAX_NAME_BYTES = 200;

const fitBytes = (text: string, max: number) => {
  let out = "";
  for (const char of text) {
    if (Buffer.byteLength(out + char) > max) break;
    out += char;
  }
  return out;
};

const safeFileName = (suggested: string) => {
  const name = NodePath.basename(suggested.replaceAll("\\", "/"))
    .replace(/[\u0000-\u001f\u007f]/g, "")
    .trim();
  if (name === "" || name === "." || name === "..") return "download";
  if (Buffer.byteLength(name) <= MAX_NAME_BYTES) return name;
  const found = NodePath.extname(name);
  const ext = Buffer.byteLength(found) <= 20 ? found : "";
  return fitBytes(name.slice(0, name.length - ext.length), MAX_NAME_BYTES - Buffer.byteLength(ext)) + ext;
};

/** Creates an empty file with a name not yet used in dir and returns its name. */
export const reserveUniqueFile = async (dir: string, suggested: string): Promise<string> => {
  await NodeFSP.mkdir(dir, { recursive: true });
  const name = safeFileName(suggested);
  const ext = NodePath.extname(name);
  const stem = ext.length > 0 && ext.length < name.length ? name.slice(0, -ext.length) : name;
  const suffix = ext.length < name.length ? ext : "";
  for (let attempt = 0; attempt < 1000; attempt++) {
    const candidate = attempt === 0 ? name : `${stem} (${attempt})${suffix}`;
    try {
      const handle = await NodeFSP.open(NodePath.join(dir, candidate), "wx");
      await handle.close();
      return candidate;
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
    }
  }
  throw new Error("Could not find a free download file name.");
};
