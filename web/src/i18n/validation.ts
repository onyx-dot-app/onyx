/**
 * Shared catalog validation and translation planning.
 *
 * Used by the Jest guard (`__tests__/catalog.test.ts`) and the pipeline CLIs
 * (`web/scripts/i18n/`). Pure functions only: callers load the catalogs and
 * the staleness meta (`catalog.meta.json`) and pass them in.
 *
 * Staleness model: `catalog.meta.json` maps each flat key to a hash of the
 * English source its translations were last synced against. One hash per key,
 * not per locale — authors update every locale together, then re-stamp with
 * `bun run i18n:stamp`. A hash mismatch means the English changed and the
 * translations were not re-synced.
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
  /** Blocking: malformed ICU, orphan keys, placeholder drift. */
  errors: CatalogIssue[];
  /** Advisory: untranslated or stale keys — the nightly pipeline fills these. */
  warnings: CatalogIssue[];
}

export interface TranslationPlan {
  /** Per locale: keys with no translation yet. */
  missing: Record<string, string[]>;
  /** Keys whose English source changed since the last stamp (all locales). */
  stale: string[];
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
  meta,
}: CatalogInput): CatalogReport {
  const errors: CatalogIssue[] = [];
  const warnings: CatalogIssue[] = [];

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
        warnings.push({
          key,
          locale,
          message: "untranslated: English fallback renders at runtime",
        });
      }
    }
  }

  const plan = planTranslationWork({ english, locales, meta });
  for (const key of plan.stale) {
    warnings.push({
      key,
      message:
        "stale: en.json changed since the last stamp — retranslate and run `bun run i18n:stamp`",
    });
  }
  for (const key of plan.orphanMetaKeys) {
    warnings.push({
      key,
      message:
        "orphan meta entry: key no longer in en.json — run `bun run i18n:stamp`",
    });
  }

  return { errors, warnings };
}

/**
 * Work list for the translation backstop: which keys each locale is missing,
 * which keys are stale everywhere, and which meta entries to prune.
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

  const stale = Object.entries(english)
    .filter(([key, source]) => {
      const stamp = meta[key];
      return stamp !== undefined && stamp !== hashMessageSource(source);
    })
    .map(([key]) => key);

  // Unstamped keys count as missing-stamp, not stale: they are new keys whose
  // translations (if any) were authored against the current English source.
  const orphanMetaKeys = Object.keys(meta).filter((key) => !(key in english));

  return { missing, stale, orphanMetaKeys };
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
