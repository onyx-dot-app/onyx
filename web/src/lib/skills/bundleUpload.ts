import type { FileWithPath } from "react-dropzone";

const ZIP_MIME_TYPE = "application/zip";
const IGNORED_FILE_NAMES = new Set([".DS_Store", "Thumbs.db"]);

export interface PreparedSkillBundle {
  file: File;
  displayName: string;
  source: "zip" | "folder";
}

export interface SkillDirectoryEntry {
  file: File;
  path: string;
}

function pathParts(file: FileWithPath): string[] {
  const rawPath = file.path || file.webkitRelativePath || file.name;
  if (rawPath.includes("\\")) {
    throw new Error(`Invalid path "${rawPath}".`);
  }

  const parts = rawPath.replace(/^\.\//, "").replace(/^\/+/, "").split("/");
  if (parts.some((part) => !part || part === "." || part === "..")) {
    throw new Error(`Invalid path "${rawPath}".`);
  }
  return parts;
}

function isIgnoredFile(parts: string[]): boolean {
  const basename = parts.at(-1);
  return (
    parts[0] === "__MACOSX" ||
    basename === undefined ||
    IGNORED_FILE_NAMES.has(basename) ||
    basename.startsWith("._")
  );
}

function isZipFile(file: File): boolean {
  return file.name.toLowerCase().endsWith(".zip");
}

export function getSkillDirectoryEntries(files: readonly FileWithPath[]): {
  directoryName: string;
  entries: SkillDirectoryEntry[];
} {
  const filesWithParts = files
    .map((file) => ({ file, parts: pathParts(file) }))
    .filter(({ parts }) => !isIgnoredFile(parts));

  if (filesWithParts.length === 0) {
    throw new Error("The selected folder is empty.");
  }

  const directoryName = filesWithParts[0]!.parts[0]!;
  const entries = filesWithParts.map(({ file, parts }) => {
    if (parts.length < 2 || parts[0] !== directoryName) {
      throw new Error("Upload one ZIP or one skill folder at a time.");
    }
    return { file, path: parts.slice(1).join("/") };
  });

  const entryPaths = new Set<string>();
  for (const entry of entries) {
    if (entryPaths.has(entry.path)) {
      throw new Error(`The folder contains duplicate path "${entry.path}".`);
    }
    entryPaths.add(entry.path);
  }
  if (!entryPaths.has("SKILL.md")) {
    throw new Error(
      "The selected folder must contain SKILL.md at its top level."
    );
  }

  return {
    directoryName,
    entries: entries.sort((left, right) => left.path.localeCompare(right.path)),
  };
}

async function packageSkillDirectory(
  directoryName: string,
  entries: readonly SkillDirectoryEntry[]
): Promise<File> {
  const { BlobReader, BlobWriter, ZipWriter } = await import("@zip.js/zip.js");
  const blobWriter = new BlobWriter(ZIP_MIME_TYPE);
  const zipWriter = new ZipWriter(blobWriter, {
    useWebWorkers: typeof Worker !== "undefined",
  });

  for (const entry of entries) {
    await zipWriter.add(entry.path, new BlobReader(entry.file), {
      lastModDate: new Date(entry.file.lastModified),
    });
  }
  await zipWriter.close();
  const zipBlob = await blobWriter.getData();
  return new File([zipBlob], `${directoryName}.zip`, { type: ZIP_MIME_TYPE });
}

export async function prepareSkillBundleUpload(
  files: readonly FileWithPath[]
): Promise<PreparedSkillBundle> {
  if (files.length === 1) {
    const [file] = files;
    const parts = pathParts(file!);
    if (parts.length === 1 && isZipFile(file!)) {
      return {
        file: file!,
        displayName: file!.name,
        source: "zip",
      };
    }
  }

  const { directoryName, entries } = getSkillDirectoryEntries(files);
  const file = await packageSkillDirectory(directoryName, entries);
  return {
    file,
    displayName: directoryName,
    source: "folder",
  };
}
