import * as languages from "linguist-languages";

interface LinguistLanguage {
  name: string;
  type: string;
  extensions?: string[];
  filenames?: string[];
}

// Build extension → language name and filename → language name maps at module load
const extensionMap = new Map<string, string>();
const filenameMap = new Map<string, string>();

for (const lang of Object.values(languages) as LinguistLanguage[]) {
  if (lang.type !== "programming") continue;

  const name = lang.name.toLowerCase();
  for (const ext of lang.extensions ?? []) {
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
