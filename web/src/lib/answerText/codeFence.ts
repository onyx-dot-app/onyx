// Adapted from T3 Code (MIT, github.com/pingdotgg/t3code).

import { getLanguageFromPath } from "@/lib/codeHighlight/language";

const FENCE_TITLE_ATTR_REGEX =
  /(?:^|\s)(?:title|file(?:name)?)=(?:"([^"]+)"|'([^']+)'|(\S+))/i;
// `src/a.ts`, `./src/a.ts`, or a dotfile such as `.gitignore`.
const FENCE_FILENAME_TOKEN_REGEX =
  /^(?:[\w@.][\w@./-]*\.[A-Za-z0-9]+|\.[\w-]+)$/;

export interface CodeFence {
  /** The highlighter language, or undefined for untagged code. */
  language: string | undefined;
  /** A file name from the info string, shown in place of the language. */
  fileName: string | undefined;
}

function titleFromMeta(meta: string | undefined): string | undefined {
  if (!meta) return undefined;
  const attrMatch = FENCE_TITLE_ATTR_REGEX.exec(meta);
  const attrTitle = attrMatch?.[1] ?? attrMatch?.[2] ?? attrMatch?.[3];
  if (attrTitle) return attrTitle;
  return meta
    .split(/\s+/)
    .find((candidate) => FENCE_FILENAME_TOKEN_REGEX.test(candidate));
}

function languageOfFileName(fileName: string): string | undefined {
  const extension = fileName.split(".").pop()?.toLowerCase();
  return getLanguageFromPath(fileName) ?? extension;
}

/**
 * Reads a fence info string: its first word (`lang`) and the rest (`meta`).
 * Supports `ts title="src/a.ts"`, `ts:src/a.ts` and a bare `src/a.ts`, whose
 * language comes from its extension.
 */
export function parseCodeFence(
  lang: string | undefined,
  meta: string | undefined
): CodeFence {
  const metaTitle = titleFromMeta(meta?.trim());
  if (!lang) return { language: undefined, fileName: metaTitle };

  const colon = lang.indexOf(":");
  if (colon > 0 && colon < lang.length - 1) {
    return {
      language: lang.slice(0, colon),
      fileName: metaTitle ?? lang.slice(colon + 1),
    };
  }
  if (FENCE_FILENAME_TOKEN_REGEX.test(lang)) {
    return { language: languageOfFileName(lang), fileName: metaTitle ?? lang };
  }
  return { language: lang, fileName: metaTitle };
}
