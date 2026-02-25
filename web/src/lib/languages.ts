import * as languages from "linguist-languages";

const LANGUAGE_EXT_PATTERN = /\.[^.]+$/;

interface LinguistLanguage {
  name: string;
  type: string;
  extensions?: string[];
  filenames?: string[];
}

interface LanguageMaps {
  extensions: Map<string, string>;
  filenames: Map<string, string>;
}

const allLanguages = Object.values(languages) as LinguistLanguage[];

// Collect extensions that linguist-languages assigns to "Markdown" so we can
// exclude them from the code-language map
const markdownExtensions = new Set(
  allLanguages
    .find((lang) => lang.name === "Markdown")
    ?.extensions?.map((ext) => ext.toLowerCase()) ?? []
);

function buildLanguageMaps(
  type: string,
  excludedExtensions?: Set<string>
): LanguageMaps {
  const extensions = new Map<string, string>();
  const filenames = new Map<string, string>();

  for (const lang of allLanguages) {
    if (lang.type !== type) continue;

    const name = lang.name.toLowerCase();
    for (const ext of lang.extensions ?? []) {
      if (excludedExtensions?.has(ext.toLowerCase())) continue;
      if (!extensions.has(ext)) {
        extensions.set(ext, name);
      }
    }
    for (const filename of lang.filenames ?? []) {
      if (!filenames.has(filename.toLowerCase())) {
        filenames.set(filename.toLowerCase(), name);
      }
    }
  }

  return { extensions, filenames };
}

function lookupLanguage(name: string, maps: LanguageMaps): string | null {
  const lower = name.toLowerCase();
  const ext = lower.match(LANGUAGE_EXT_PATTERN)?.[0];
  return (ext && maps.extensions.get(ext)) ?? maps.filenames.get(lower) ?? null;
}

const codeMaps = buildLanguageMaps("programming", markdownExtensions);
const dataMaps = buildLanguageMaps("data");

/**
 * Returns the language name for a given file name, or null if it's not a
 * recognised code file. Looks up by extension first, then by exact filename
 * (e.g. "Dockerfile", "Makefile"). Runs in O(1).
 */
export function getCodeLanguage(name: string): string | null {
  return lookupLanguage(name, codeMaps);
}

/**
 * Returns the language name for a given file name if it's a recognised
 * "data" type in linguist-languages (e.g. JSON, YAML, TOML, XML).
 * Returns null otherwise. Runs in O(1).
 */
export function getDataLanguage(name: string): string | null {
  return lookupLanguage(name, dataMaps);
}

/**
 * Returns true if the file name has a Markdown extension (as defined by
 * linguist-languages) and should be rendered as rich text rather than code.
 */
export function isMarkdownFile(name: string): boolean {
  const ext = name.toLowerCase().match(LANGUAGE_EXT_PATTERN)?.[0];
  return !!ext && markdownExtensions.has(ext);
}
