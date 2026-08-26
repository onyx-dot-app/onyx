/**
 * Guards the message catalogs via the shared validator (`@/i18n/validation`),
 * which the pipeline CLIs in `web/scripts/i18n/` also use:
 * - blocking: every message parses as ICU, no orphan keys, and shared keys use
 *   exactly the same ICU placeholders as the English source;
 * - advisory: untranslated or stale keys are reported, not failed — authors
 *   translate by hand and the nightly translation workflow backfills the rest.
 */
import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import es from "@/i18n/messages/es.json";
import fr from "@/i18n/messages/fr.json";
import pt from "@/i18n/messages/pt.json";
import meta from "@/i18n/catalog.meta.json";
import {
  buildStamp,
  flattenMessages,
  hashMessageSource,
  planTranslationWork,
  validateCatalogs,
  type MessageTree,
} from "@/i18n/validation";

describe("i18n message catalogs", () => {
  const report = validateCatalogs({
    english: flattenMessages(en as MessageTree),
    locales: {
      de: flattenMessages(de as MessageTree),
      es: flattenMessages(es as MessageTree),
      fr: flattenMessages(fr as MessageTree),
      pt: flattenMessages(pt as MessageTree),
    },
    meta,
  });

  test("no blocking issues: valid ICU, no orphans, placeholder parity", () => {
    expect(report.errors).toEqual([]);
  });

  test("reports untranslated and stale keys without failing", () => {
    if (report.warnings.length > 0) {
      const preview = report.warnings
        .slice(0, 20)
        .map((warning) =>
          warning.locale
            ? `${warning.locale}:${warning.key} — ${warning.message}`
            : `${warning.key} — ${warning.message}`
        );
      console.warn(
        `[i18n] ${report.warnings.length} advisory issue(s); ` +
          `the nightly translation workflow repairs these:\n` +
          preview.join("\n")
      );
    }
    expect(true).toBe(true);
  });
});

describe("translation planning", () => {
  const english = { "a.one": "One", "a.two": "Two {name}", "a.three": "Three" };
  const meta = {
    "a.one": hashMessageSource("One"),
    "a.two": hashMessageSource("an older English source"),
    "a.gone": hashMessageSource("Gone"),
  };
  const locales = {
    es: { "a.one": "Uno", "a.two": "Dos {name}" },
    fr: { "a.one": "Un", "a.two": "Deux {name}", "a.three": "Trois" },
  };

  test("plans missing, stale, and orphan-meta work", () => {
    const plan = planTranslationWork({ english, locales, meta });
    expect(plan.missing).toEqual({ es: ["a.three"], fr: [] });
    expect(plan.stale).toEqual(["a.two"]);
    expect(plan.orphanMetaKeys).toEqual(["a.gone"]);
  });

  test("stamps fully translated keys, keeps partial keys unstamped", () => {
    expect(buildStamp({ english, locales, meta })).toEqual({
      "a.one": hashMessageSource("One"),
      "a.two": hashMessageSource("Two {name}"),
    });
  });

  test("keepStaleKeys preserves the previous stamp for failed keys", () => {
    const stamp = buildStamp({ english, locales, meta }, new Set(["a.two"]));
    expect(stamp["a.two"]).toBe(hashMessageSource("an older English source"));
  });

  test("flags stale and untranslated keys as warnings, not errors", () => {
    const report = validateCatalogs({ english, locales, meta });
    expect(report.errors).toEqual([]);
    const warned = report.warnings.map((warning) => warning.key).sort();
    expect(warned).toEqual(["a.gone", "a.three", "a.two"]);
  });
});
