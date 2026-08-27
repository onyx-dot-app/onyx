/**
 * Guards what the type system cannot see inside the message strings:
 * - every message in every locale parses as ICU,
 * - each translation uses exactly the same ICU placeholders as its English
 *   source.
 *
 * Key parity (no missing or extra keys per locale) is a compile-time check —
 * see src/i18n/messages/keyParity.ts.
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
import ja from "@/i18n/messages/ja.json";
import ko from "@/i18n/messages/ko.json";
import pt from "@/i18n/messages/pt.json";
import zh from "@/i18n/messages/zh.json";

type MessageTree = { [key: string]: string | MessageTree };

const TARGET_LOCALES: Record<string, MessageTree> = {
  de,
  es,
  fr,
  ja,
  ko,
  pt,
  zh,
};

function flatten(tree: MessageTree, prefix = ""): Record<string, string> {
  const flat: Record<string, string> = {};
  for (const [key, value] of Object.entries(tree)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (typeof value === "string") {
      flat[path] = value;
    } else {
      Object.assign(flat, flatten(value, path));
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

function sortedArguments(message: string): string[] {
  return Array.from(collectArguments(parse(message), new Set<string>())).sort();
}

const flatEnglish = flatten(en as MessageTree);

describe("i18n message catalogs", () => {
  test("every English message is valid ICU", () => {
    for (const [key, message] of Object.entries(flatEnglish)) {
      expect(() => parse(message)).not.toThrow();
      expect(key).not.toBe("");
    }
  });

  for (const [locale, catalog] of Object.entries(TARGET_LOCALES)) {
    test(`${locale}: every message is valid ICU with the same placeholders as English`, () => {
      for (const [key, message] of Object.entries(flatten(catalog))) {
        const englishMessage = flatEnglish[key];
        // Key parity is compile-time checked (messages/keyParity.ts).
        if (englishMessage === undefined) continue;

        expect(() => parse(message)).not.toThrow();
        expect({ key, placeholders: sortedArguments(message) }).toEqual({
          key,
          placeholders: sortedArguments(englishMessage),
        });
      }
    });
  }
});
