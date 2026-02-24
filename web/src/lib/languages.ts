import * as languages from "linguist-languages";

interface LinguistLanguage {
  name: string;
  type: string;
  extensions?: string[];
  filenames?: string[];
}

const allLanguages = Object.values(languages) as LinguistLanguage[];

// Collect extensions that linguist-languages assigns to "Markdown" so we can
// exclude them from the code-language map
const markdownExtensions = new Set(
  allLanguages
    .find((lang) => lang.name === "Markdown")
    ?.extensions?.map((ext) => ext.toLowerCase()) ?? []
);

// Build extension → language name and filename → language name maps at module load
const extensionMap = new Map<string, string>();
const filenameMap = new Map<string, string>();

for (const lang of allLanguages) {
  if (lang.type !== "programming") continue;

  const name = lang.name.toLowerCase();
  for (const ext of lang.extensions ?? []) {
    if (markdownExtensions.has(ext.toLowerCase())) continue;
    // First language to claim an extension wins
    if (!extensionMap.has(ext)) {
      extensionMap.set(ext, name);
    }
  }
  for (const filename of lang.filenames ?? []) {
    if (!filenameMap.has(filename.toLowerCase())) {
      filenameMap.set(filename.toLowerCase(), name);
    }
  }
}

/**
 * Returns the language name for a given file name, or null if it's not a
 * recognised code file. Looks up by extension first, then by exact filename
 * (e.g. "Dockerfile", "Makefile"). Runs in O(1).
 */
export function getCodeLanguage(name: string): string | null {
  const lower = name.toLowerCase();
  const ext = lower.match(/\.[^.]+$/)?.[0];
  return (ext && extensionMap.get(ext)) ?? filenameMap.get(lower) ?? null;
}

/**
 * Returns true if the file name has a Markdown extension (as defined by
 * linguist-languages) and should be rendered as rich text rather than code.
 */
export function isMarkdownFile(name: string): boolean {
  const ext = name.toLowerCase().match(/\.[^.]+$/)?.[0];
  return !!ext && markdownExtensions.has(ext);
}
