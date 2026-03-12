import * as languages from "linguist-languages";

const LANGUAGE_EXT_PATTERN = /\.[^.]+$/;

interface LinguistLanguage {
  name: string;
  type: string;
  extensions?: string[];
  filenames?: string[];
  codemirrorMimeType?: string;
}

interface LanguageMaps {
  extensions: Map<string, string>;
  filenames: Map<string, string>;
}

// Explicit winners for extensions claimed by multiple linguist-languages entries
// where the "most extensions" heuristic below picks the wrong language.
const EXTENSION_OVERRIDES: Record<string, string> = {
  ".h": "c",
  ".inc": "php",
  ".m": "objective-c",
  ".re": "reason",
  ".rs": "rust",
};

// Sort so that languages with more extensions (i.e. more general-purpose) win
// when multiple languages claim the same extension (e.g. Ecmarkup vs HTML both
// claim .html — HTML should win because it's the canonical language for that
// extension). Known mis-rankings are patched by EXTENSION_OVERRIDES above.
const allLanguages = (Object.values(languages) as LinguistLanguage[]).sort(
  (a, b) => (b.extensions?.length ?? 0) - (a.extensions?.length ?? 0)
);

// Collect extensions that linguist-languages assigns to "Markdown" so we can
// exclude them from the code-language map
const markdownExtensions = new Set(
  allLanguages
    .find((lang) => lang.name === "Markdown")
    ?.extensions?.map((ext) => ext.toLowerCase()) ?? []
);

function buildLanguageMaps(
  types: string[],
  excludedExtensions?: Set<string>
): LanguageMaps {
  const typeSet = new Set(types);
  const extensions = new Map<string, string>();
  const filenames = new Map<string, string>();

  if (typeSet.has("programming") || typeSet.has("markup")) {
    for (const [ext, lang] of Object.entries(EXTENSION_OVERRIDES)) {
      if (excludedExtensions?.has(ext.toLowerCase())) continue;
      extensions.set(ext, lang);
    }
  }

  for (const lang of allLanguages) {
    if (!typeSet.has(lang.type)) continue;

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

const codeMaps = buildLanguageMaps(
  ["programming", "markup"],
  markdownExtensions
);
const dataMaps = buildLanguageMaps(["data"]);

/**
 * Returns the language name for a given file name, or null if it's not a
 * recognised code or markup file (programming + markup types from
 * linguist-languages, e.g. Python, HTML, CSS, Vue). Looks up by extension
 * first, then by exact filename (e.g. "Dockerfile", "Makefile"). Runs in O(1).
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

const mimeToLanguage = new Map<string, string>();
for (const lang of allLanguages) {
  if (lang.codemirrorMimeType && !mimeToLanguage.has(lang.codemirrorMimeType)) {
    mimeToLanguage.set(lang.codemirrorMimeType, lang.name.toLowerCase());
  }
}

/**
 * Returns the language name for a given MIME type using the codemirrorMimeType
 * field from linguist-languages (~297 entries). Returns null if unrecognised.
 */
export function getLanguageByMime(mime: string): string | null {
  const base = mime.split(";")[0];
  if (!base) return null;
  return mimeToLanguage.get(base.trim().toLowerCase()) ?? null;
}
