import { PLUGIN_MANIFEST_PATHS } from "@/lib/plugins/upload";

const ZIP_MIME_TYPE = "application/zip";
const IGNORED_FILE_NAMES = new Set([".DS_Store", "Thumbs.db"]);

// react-dropzone attaches `path` to dropped files, but types its callbacks with
// plain `File`. Callers can pass either.
export type SkillUploadFile = File & { readonly path?: string };

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
  file: SkillUploadFile;
  parts: string[];
}

function pathParts(file: SkillUploadFile): string[] {
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
  files: readonly SkillUploadFile[]
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

/** A folder without SKILL.md, or for a plugin upload also without a plugin
 * manifest, at its top level; the picker words it in the user's language. */
export class SkillFolderRootError extends Error {
  constructor(readonly upload: "skill" | "plugin") {
    super(
      upload === "plugin"
        ? "The selected folder must contain SKILL.md or a plugin.json manifest at its top level."
        : "The selected folder must contain SKILL.md at its top level."
    );
  }
}

export interface PrepareSkillBundleOptions {
  /** Also take a folder with a plugin manifest at its top level. */
  allowPlugin?: boolean;
}

export async function prepareSkillBundleUpload(
  files: readonly SkillUploadFile[],
  { allowPlugin = false }: PrepareSkillBundleOptions = {}
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
  const isPlugin =
    allowPlugin && PLUGIN_MANIFEST_PATHS.some((path) => entryPaths.has(path));
  if (!entryPaths.has("SKILL.md") && !isPlugin) {
    throw new SkillFolderRootError(allowPlugin ? "plugin" : "skill");
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
  files: readonly SkillUploadFile[]
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

// The per-user write limits of `backend/onyx/skills/limits.py`. A merge stops
// before it holds more than the server would take.
const MERGE_MAX_BYTES = 500 * 1024 * 1024;
const MERGE_MAX_FILES = 5_000;

/** A merge past one of the limits; the page words it in the user's language. */
export class SkillMergeLimitError extends Error {
  constructor(
    readonly limit: "files" | "bytes",
    readonly max: number
  ) {
    super(`The skill files are past the ${limit} limit of ${max}.`);
  }
}

export const SKILL_MERGE_MAX_MB = MERGE_MAX_BYTES / (1024 * 1024);

class MergeBudget {
  private bytes = 0;
  private files = 0;

  take(bytes: number): void {
    this.bytes += bytes;
    this.files += 1;
    if (this.files > MERGE_MAX_FILES)
      throw new SkillMergeLimitError("files", MERGE_MAX_FILES);
    if (this.bytes > MERGE_MAX_BYTES)
      throw new SkillMergeLimitError("bytes", SKILL_MERGE_MAX_MB);
  }
}

/** The files in one upload, by their path in the skill. A SKILL.md bundle
 * gives its SKILL.md at the root, with the files beside it, so the server
 * keeps the frontmatter fields that the editor does not show. */
async function filesOf(
  upload: PreparedSkillFilesUpload,
  budget: MergeBudget
): Promise<SkillDirectoryEntry[]> {
  if (!isZipFile(upload.file)) {
    budget.take(upload.file.size);
    const path = isSkillMd(upload.file)
      ? "SKILL.md"
      : (upload.entries?.[0]?.path ?? upload.file.name);
    return [{ file: upload.file, path }];
  }
  const { BlobReader, BlobWriter, ZipReader } = await import("@zip.js/zip.js");
  const reader = new ZipReader(new BlobReader(upload.file));
  try {
    const entries = (await reader.getEntries()).filter(
      (entry) => !entry.directory
    );
    // A bundle's files sit beside its SKILL.md, which may be in one folder.
    const skillMd = upload.containsSkillMd
      ? entries.find(
          (entry) =>
            entry.filename.split("/").at(-1)?.toLowerCase() === "skill.md"
        )
      : undefined;
    const root = skillMd
      ? skillMd.filename.slice(0, skillMd.filename.lastIndexOf("/") + 1)
      : "";
    const wanted = entries.filter((entry) => {
      if (!entry.filename.startsWith(root)) return false;
      const path = entry.filename.slice(root.length);
      const basename = path.split("/").at(-1) ?? path;
      return !IGNORED_FILE_NAMES.has(basename) && !path.startsWith("__MACOSX/");
    });
    // Check the sizes the archive declares before unpacking any of it.
    const declared = new MergeBudget();
    for (const entry of wanted) declared.take(entry.uncompressedSize);
    const files: SkillDirectoryEntry[] = [];
    for (const entry of wanted) {
      const path =
        entry === skillMd ? "SKILL.md" : entry.filename.slice(root.length);
      const blob = await entry.getData(new BlobWriter());
      budget.take(blob.size);
      files.push({
        file: new File([blob], path.split("/").at(-1) ?? path, {
          lastModified: entry.lastModDate.getTime(),
        }),
        path,
      });
    }
    return files;
  } finally {
    await reader.close();
  }
}

/** One ZIP of every upload's files, a later upload replacing an earlier file
 * with the same path, without the removed paths. Undefined when no file is
 * left. Stops at the server's per-user write limits. */
export async function mergeSkillFilesUploads(
  uploads: readonly PreparedSkillFilesUpload[],
  removed: ReadonlySet<string>
): Promise<File | undefined> {
  const budget = new MergeBudget();
  const byPath = new Map<string, SkillDirectoryEntry>();
  for (const upload of uploads)
    for (const entry of await filesOf(upload, budget))
      byPath.set(entry.path, entry);
  const kept = [...byPath.values()]
    .filter((entry) => !removed.has(entry.path))
    .sort((left, right) => left.path.localeCompare(right.path));
  return kept.length > 0 ? packageFiles("skill-files.zip", kept) : undefined;
}
