/**
 * Guards the message catalogs:
 * - every message in every locale parses as ICU,
 * - non-English catalogs contain no keys that are missing from en.json,
 * - shared keys use exactly the same ICU placeholders as the English source.
 *
 * Keys present in en.json but not yet translated are reported, not failed —
 * that is the expected lag window before the translation pipeline runs.
 */
import {
  parse,
  TYPE,
  type MessageFormatElement,
} from "@formatjs/icu-messageformat-parser";

import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import es from "@/i18n/messages/es.json";
import fr from "@/i18n/messages/fr.json";
import pt from "@/i18n/messages/pt.json";

type MessageTree = { [key: string]: string | MessageTree };

const TARGET_LOCALES: Record<string, MessageTree> = { de, es, fr, pt };

function flatten(tree: MessageTree, prefix = ""): Map<string, string> {
  const flat = new Map<string, string>();
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") {
      flat.set(path, value);
    } else {
      for (const [nestedPath, nestedValue] of flatten(value, path)) {
        flat.set(nestedPath, nestedValue);
      }
    }
  }
  return flat;
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

const flatEnglish = flatten(en as MessageTree);

describe("i18n message catalogs", () => {
  test("every English message is valid ICU", () => {
    for (const [key, message] of flatEnglish) {
      expect(() => parse(message)).not.toThrow();
      expect(key).not.toBe("");
    }
  });

  for (const [locale, catalog] of Object.entries(TARGET_LOCALES)) {
    describe(locale, () => {
      const flatLocale = flatten(catalog);

      test("has no keys that are missing from en.json", () => {
        const orphans = [...flatLocale.keys()].filter(
          (key) => !flatEnglish.has(key)
        );
        expect(orphans).toEqual([]);
      });

      test("every message is valid ICU with the same placeholders as English", () => {
        for (const [key, message] of flatLocale) {
          const englishMessage = flatEnglish.get(key);
          if (englishMessage === undefined) continue; // covered by orphan test

          let elements: MessageFormatElement[];
          expect(() => (elements = parse(message))).not.toThrow();
          const localeArguments = collectArguments(parse(message), new Set());
          const englishArguments = collectArguments(
            parse(englishMessage),
            new Set()
          );
          expect({ key, placeholders: [...localeArguments].sort() }).toEqual({
            key,
            placeholders: [...englishArguments].sort(),
          });
        }
      });

      test("reports untranslated keys without failing", () => {
        const untranslated = [...flatEnglish.keys()].filter(
          (key) => !flatLocale.has(key)
        );
        if (untranslated.length > 0) {
          console.warn(
            `[i18n] ${locale}: ${untranslated.length} untranslated key(s) ` +
              `(English fallback renders until the translation pipeline runs): ` +
              untranslated.slice(0, 20).join(", ")
          );
        }
        expect(true).toBe(true);
      });
    });
  }
});
