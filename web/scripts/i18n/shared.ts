/** Filesystem plumbing shared by the i18n pipeline CLIs. */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  flattenMessages,
  type CatalogInput,
  type CatalogMeta,
  type MessageTree,
} from "@/i18n/validation";
import { DEFAULT_LOCALE, SUPPORTED_LOCALES } from "@/i18n/config";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const I18N_DIR = path.join(SCRIPT_DIR, "..", "..", "src", "i18n");
export const MESSAGES_DIR = path.join(I18N_DIR, "messages");
export const META_PATH = path.join(I18N_DIR, "catalog.meta.json");
export const GLOSSARY_PATH = path.join(SCRIPT_DIR, "glossary.json");

export const TARGET_LOCALES = SUPPORTED_LOCALES.filter(
  (locale) => locale !== DEFAULT_LOCALE
);

export interface Glossary {
  doNotTranslate: string[];
  terms: Record<string, Record<string, string>>;
  localeStyle: Record<string, string>;
}

export function readJsonFile<T>(filePath: string): T {
  // SAFETY: callers pass the schema their checked-in JSON file follows; the
  // validator surfaces any drift immediately after loading.
  return JSON.parse(fs.readFileSync(filePath, "utf8")) as T;
}

export function writeJsonFile(
  filePath: string,
  value: CatalogMeta | MessageTree
): void {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`);
}

export function messagesPath(locale: string): string {
  return path.join(MESSAGES_DIR, `${locale}.json`);
}

export function loadMessageTree(locale: string): MessageTree {
  return readJsonFile<MessageTree>(messagesPath(locale));
}

export function loadCatalogs(): CatalogInput {
  const english = flattenMessages(loadMessageTree(DEFAULT_LOCALE));
  const locales: Record<string, Record<string, string>> = {};
  for (const locale of TARGET_LOCALES) {
    locales[locale] = flattenMessages(loadMessageTree(locale));
  }
  const meta = fs.existsSync(META_PATH)
    ? readJsonFile<CatalogMeta>(META_PATH)
    : {};
  return { english, locales, meta };
}

/**
 * Rebuild a locale's nested message tree in en.json's key order so catalog
 * diffs stay aligned across locales. Keys the locale does not have are left
 * out (English fallback renders at runtime).
 */
export function toNestedInEnglishOrder(
  englishTree: MessageTree,
  flat: Record<string, string>,
  prefix = ""
): MessageTree {
  const nested: MessageTree = {};
  for (const [key, englishValue] of Object.entries(englishTree)) {
    const path_ = prefix ? `${prefix}.${key}` : key;
    if (typeof englishValue === "string") {
      const translation = flat[path_];
      if (translation !== undefined) {
        nested[key] = translation;
      }
    } else {
      const child = toNestedInEnglishOrder(englishValue, flat, path_);
      if (Object.keys(child).length > 0) {
        nested[key] = child;
      }
    }
  }
  return nested;
}
