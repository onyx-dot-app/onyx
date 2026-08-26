/**
 * Guards the message catalogs via the shared validator (`@/i18n/validation`),
 * which the pipeline CLIs in `web/scripts/i18n/` also use. Blocking for
 * authors: every message parses as ICU, no orphan keys, every en.json key is
 * translated in every locale, and placeholders match the English source.
 * Review bookkeeping (which keys the weekly QA run still needs to visit) is
 * planning data in `catalog.meta.json`, owned by the pipeline — never a test
 * failure.
 */
import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import es from "@/i18n/messages/es.json";
import fr from "@/i18n/messages/fr.json";
import pt from "@/i18n/messages/pt.json";
import {
  buildStamp,
  flattenMessages,
  hashMessageSource,
  planTranslationWork,
  validateCatalogs,
  type MessageTree,
} from "@/i18n/validation";

describe("i18n message catalogs", () => {
  test("valid ICU, full key parity, placeholder parity", () => {
    const report = validateCatalogs({
      english: flattenMessages(en as MessageTree),
      locales: {
        de: flattenMessages(de as MessageTree),
        es: flattenMessages(es as MessageTree),
        fr: flattenMessages(fr as MessageTree),
        pt: flattenMessages(pt as MessageTree),
      },
    });
    expect(report.errors).toEqual([]);
  });
});

describe("QA planning", () => {
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

  test("missing translations are blocking errors", () => {
    const report = validateCatalogs({ english, locales });
    expect(report.errors).toEqual([
      {
        key: "a.three",
        locale: "es",
        message: expect.stringContaining("untranslated"),
      },
    ]);
  });

  test("plans missing, changed, never-reviewed, and orphan-meta work", () => {
    const plan = planTranslationWork({ english, locales, meta });
    expect(plan.missing).toEqual({ es: ["a.three"], fr: [] });
    expect(plan.stale).toEqual(["a.two"]);
    expect(plan.unreviewed).toEqual(["a.three"]);
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
});
