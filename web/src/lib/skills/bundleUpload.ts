import type { FileWithPath } from "react-dropzone";

const ZIP_MIME_TYPE = "application/zip";
const IGNORED_FILE_NAMES = new Set([".DS_Store", "Thumbs.db"]);

export interface PreparedSkillBundle {
  file: File;
  displayName: string;
  source: "zip" | "skill-md" | "folder";
}

export interface PreparedSkillFilesUpload {
  file: File;
  displayName: string;
  entries: { path: string; size: number }[] | null;
  containsSkillMd: boolean;
}

interface SkillDirectoryEntry {
  file: File;
  path: string;
}

interface SelectedFile {
  file: FileWithPath;
  parts: string[];
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

function isZipFile(file: File): boolean {
  return file.name.toLowerCase().endsWith(".zip");
}

function isSkillMd(file: File): boolean {
  return file.name.toLowerCase() === "skill.md";
}

function selectedFilesWithParts(
  files: readonly FileWithPath[]
): SelectedFile[] {
  return files
    .map((file) => ({ file, parts: pathParts(file) }))
    .filter(({ parts }) => {
      const basename = parts.at(-1);
      return (
        parts[0] !== "__MACOSX" &&
        basename !== undefined &&
        !IGNORED_FILE_NAMES.has(basename) &&
        !basename.startsWith("._")
      );
    });
}

async function packageFiles(
  archiveName: string,
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
  return new File([zipBlob], archiveName, { type: ZIP_MIME_TYPE });
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
    if (parts.length === 1 && isSkillMd(file!)) {
      return {
        file: file!,
        displayName: file!.name,
        source: "skill-md",
      };
    }
  }

  const filesWithParts = selectedFilesWithParts(files);
  if (filesWithParts.length === 0) {
    throw new Error("The selected folder is empty.");
  }

  const directoryName = filesWithParts[0]!.parts[0]!;
  const entries = filesWithParts.map(({ file, parts }) => {
    if (parts.length < 2 || parts[0] !== directoryName) {
      throw new Error("Upload one ZIP, SKILL.md, or skill folder at a time.");
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

  entries.sort((left, right) => left.path.localeCompare(right.path));
  const file = await packageFiles(`${directoryName}.zip`, entries);
  return {
    file,
    displayName: directoryName,
    source: "folder",
  };
}

export async function prepareSkillFilesUpload(
  files: readonly FileWithPath[]
): Promise<PreparedSkillFilesUpload> {
  const entries = selectedFilesWithParts(files).map(({ file, parts }) => ({
    file,
    path: parts.join("/"),
  }));

  if (entries.length === 0) {
    throw new Error("The selected upload is empty.");
  }

  if (entries.length === 1 && entries[0]!.path === entries[0]!.file.name) {
    const entry = entries[0]!;
    let containsSkillMd = isSkillMd(entry.file);
    if (isZipFile(entry.file)) {
      const { BlobReader, ZipReader } = await import("@zip.js/zip.js");
      const reader = new ZipReader(new BlobReader(entry.file));
      try {
        const zipEntries = await reader.getEntries();
        containsSkillMd = zipEntries.some(
          (zipEntry) =>
            !zipEntry.directory &&
            zipEntry.filename.split("/").at(-1)?.toLowerCase() === "skill.md"
        );
      } finally {
        await reader.close();
      }
    }
    return {
      file: entry.file,
      displayName: entry.file.name,
      entries:
        isZipFile(entry.file) || isSkillMd(entry.file)
          ? null
          : [{ path: entry.path, size: entry.file.size }],
      containsSkillMd,
    };
  }

  if (entries.some((entry) => isZipFile(entry.file))) {
    throw new Error("Upload ZIP files separately from other files or folders.");
  }

  const paths = new Set<string>();
  for (const entry of entries) {
    if (paths.has(entry.path)) {
      throw new Error(`The upload contains duplicate path "${entry.path}".`);
    }
    paths.add(entry.path);
  }

  return {
    file: await packageFiles("skill-files.zip", entries),
    displayName:
      entries.length === 1
        ? entries[0]!.path
        : `${entries.length} items selected`,
    entries: entries.map((entry) => ({
      path: entry.path,
      size: entry.file.size,
    })),
    containsSkillMd: entries.some(
      (entry) => entry.path.split("/").at(-1)?.toLowerCase() === "skill.md"
    ),
  };
}
