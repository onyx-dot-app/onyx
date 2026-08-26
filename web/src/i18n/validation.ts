/**
 * Shared catalog validation and QA planning.
 *
 * Used by the Jest guard (`__tests__/catalog.test.ts`) and the pipeline CLIs
 * (`web/scripts/i18n/`). Pure functions only: callers load the catalogs and
 * the review meta (`catalog.meta.json`) and pass them in.
 *
 * Validation is the blocking author-facing contract: every English key has a
 * translation in every locale with the same ICU shape. The review meta is
 * owned by the weekly QA pipeline, not by authors: it maps each flat key to a
 * hash of the English source the translations were last QA-reviewed against,
 * so the weekly run only revisits new keys (no stamp) and changed keys (hash
 * mismatch).
 */
import {
  parse,
  TYPE,
  type MessageFormatElement,
} from "@formatjs/icu-messageformat-parser";

export type MessageTree = { [key: string]: string | MessageTree };
export type FlatMessages = Record<string, string>;
export type CatalogMeta = Record<string, string>;

export interface CatalogIssue {
  key: string;
  message: string;
  locale?: string;
}

export interface CatalogReport {
  /** Blocking: malformed ICU, orphan keys, untranslated keys, placeholder drift. */
  errors: CatalogIssue[];
}

export interface TranslationPlan {
  /** Per locale: keys with no translation yet (normally blocked by CI). */
  missing: Record<string, string[]>;
  /** Keys whose English source changed since the last QA review (all locales). */
  stale: string[];
  /** Keys never QA-reviewed: present in en.json but absent from the meta. */
  unreviewed: string[];
  /** Meta entries for keys that no longer exist in en.json. */
  orphanMetaKeys: string[];
}

export function flattenMessages(tree: MessageTree, prefix = "") {
  const flat: FlatMessages = {};
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") {
      flat[path] = value;
    } else {
      Object.assign(flat, flattenMessages(value, path));
    }
  }
  return flat;
}

/**
 * FNV-1a 32-bit over UTF-16 code units. Not cryptographic — it only needs to
 * be deterministic and cheap so `catalog.meta.json` diffs stay one line per
 * changed key.
 */
export function hashMessageSource(value: string): string {
  let hash = 0x811c9dc5;
  for (let index = 0; index < value.length; index++) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, "0");
}

function collectArguments(
  elements: MessageFormatElement[],
  into: Set<string>
): Set<string> {
  for (const element of elements) {
    switch (element.type) {
      case TYPE.argument:
      case TYPE.number:
      case TYPE.date:
      case TYPE.time:
        into.add(element.value);
        break;
      case TYPE.plural:
      case TYPE.select:
        into.add(element.value);
        for (const option of Object.values(element.options)) {
          collectArguments(option.value, into);
        }
        break;
      case TYPE.tag:
        into.add(element.value);
        collectArguments(element.children, into);
        break;
      default:
        break;
    }
  }
  return into;
}

/** Sorted ICU argument/tag names of a message. Throws on malformed ICU. */
export function icuArguments(message: string): string[] {
  return Array.from(collectArguments(parse(message), new Set<string>())).sort();
}

export interface CatalogInput {
  english: FlatMessages;
  locales: Record<string, FlatMessages>;
  meta: CatalogMeta;
}

export function validateCatalogs({
  english,
  locales,
}: Pick<CatalogInput, "english" | "locales">): CatalogReport {
  const errors: CatalogIssue[] = [];

  const englishArguments: Record<string, string[]> = {};
  for (const [key, message] of Object.entries(english)) {
    try {
      englishArguments[key] = icuArguments(message);
    } catch (parseError) {
      errors.push({
        key,
        locale: "en",
        message: `invalid ICU: ${String(parseError)}`,
      });
    }
  }

  for (const [locale, catalog] of Object.entries(locales)) {
    for (const [key, message] of Object.entries(catalog)) {
      if (!(key in english)) {
        errors.push({
          key,
          locale,
          message: "orphan key: not present in en.json",
        });
        continue;
      }
      let localeArguments: string[];
      try {
        localeArguments = icuArguments(message);
      } catch (parseError) {
        errors.push({
          key,
          locale,
          message: `invalid ICU: ${String(parseError)}`,
        });
        continue;
      }
      const expected = englishArguments[key];
      if (
        expected !== undefined &&
        JSON.stringify(localeArguments) !== JSON.stringify(expected)
      ) {
        errors.push({
          key,
          locale,
          message:
            `placeholder mismatch: [${localeArguments.join(", ")}] ` +
            `vs English [${expected.join(", ")}]`,
        });
      }
    }

    for (const key of Object.keys(english)) {
      if (!(key in catalog)) {
        errors.push({
          key,
          locale,
          message:
            "untranslated: every en.json key needs a translation in every locale",
        });
      }
    }
  }

  return { errors };
}

/**
 * Work list for the weekly QA run: which keys each locale is missing, which
 * keys changed since their last review, which were never reviewed, and which
 * meta entries to prune.
 */
export function planTranslationWork({
  english,
  locales,
  meta,
}: CatalogInput): TranslationPlan {
  const missing: Record<string, string[]> = {};
  for (const [locale, catalog] of Object.entries(locales)) {
    missing[locale] = Object.keys(english).filter((key) => !(key in catalog));
  }

  const stale: string[] = [];
  const unreviewed: string[] = [];
  for (const [key, source] of Object.entries(english)) {
    const stamp = meta[key];
    if (stamp === undefined) {
      unreviewed.push(key);
    } else if (stamp !== hashMessageSource(source)) {
      stale.push(key);
    }
  }

  const orphanMetaKeys = Object.keys(meta).filter((key) => !(key in english));

  return { missing, stale, unreviewed, orphanMetaKeys };
}

/**
 * The stamp `catalog.meta.json` should contain for the current catalogs: a
 * fresh hash for every key translated in every locale; the previous stamp (if
 * any) for partially translated keys so they stay stale until filled.
 *
 * `keepStaleKeys`: keys whose translations are known to still lag the English
 * source (e.g. a batch the translator failed to fill) — these keep their
 * previous stamp instead of a fresh one.
 */
export function buildStamp(
  { english, locales, meta }: CatalogInput,
  keepStaleKeys: ReadonlySet<string> = new Set()
) {
  const stamp: CatalogMeta = {};
  const entries = Object.entries(english).sort(([a], [b]) =>
    a.localeCompare(b)
  );
  for (const [key, source] of entries) {
    const everywhere = Object.values(locales).every(
      (catalog) => key in catalog
    );
    const previous = meta[key];
    if (everywhere && !keepStaleKeys.has(key)) {
      stamp[key] = hashMessageSource(source);
    } else if (previous !== undefined) {
      stamp[key] = previous;
    }
  }
  return stamp;
}
