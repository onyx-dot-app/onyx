/**
 * Backstop translator for the message catalogs.
 *
 * Authors translate every key they touch by hand (web/AGENTS.md §7). This
 * script repairs whatever slipped through: it fills keys missing from target
 * locales and retranslates keys whose English source changed since the last
 * stamp, then rewrites `catalog.meta.json`. The nightly i18n-translate
 * workflow runs it and opens a reviewed PR with the result.
 *
 *   ANTHROPIC_API_KEY=... bun run i18n:translate
 *   bun run i18n:translate -- --dry-run   # print the work list, no API calls
 */
import {
  buildStamp,
  icuArguments,
  planTranslationWork,
  validateCatalogs,
  type FlatMessages,
} from "@/i18n/validation";
import {
  GLOSSARY_PATH,
  loadCatalogs,
  loadMessageTree,
  messagesPath,
  META_PATH,
  readJsonFile,
  TARGET_LOCALES,
  toNestedInEnglishOrder,
  writeJsonFile,
  type Glossary,
} from "./shared";
import { DEFAULT_LOCALE } from "@/i18n/config";

const BATCH_SIZE = 40;
const MAX_ATTEMPTS = 2;
const MODEL = process.env.ONYX_I18N_TRANSLATION_MODEL ?? "claude-sonnet-5";

function buildPrompt(
  locale: string,
  glossary: Glossary,
  batch: FlatMessages
): string {
  const termLines = Object.entries(glossary.terms)
    .map(([term, byLocale]) => {
      const translation = byLocale[locale];
      return translation === undefined ? null : `"${term}" → "${translation}"`;
    })
    .filter((line): line is string => line !== null);

  return [
    "You translate UI strings for Onyx, an enterprise AI search and chat product.",
    "",
    `Target locale: "${locale}". ${glossary.localeStyle[locale] ?? ""}`,
    "",
    "Rules:",
    "- Values are ICU MessageFormat. Keep every {argument} name, plural/select structure, and <tag></tag> name exactly as in the source; translate only the human-readable text.",
    `- Keep brand and product names in English (LinkedIn, YouTube, Slack, ${glossary.doNotTranslate.join(", ")}, ...).`,
    ...(termLines.length > 0
      ? [`- Glossary, use these exact translations: ${termLines.join("; ")}`]
      : []),
    "- Keys are stable identifiers whose dot-path hints at the UI context (namespace.section.element.role). Never alter keys.",
    "- Match the tone and brevity of product UI copy.",
    "",
    "Translate the values of this JSON object:",
    JSON.stringify(batch, null, 2),
    "",
    "Reply with only a JSON object containing exactly the same keys, with translated values.",
  ].join("\n");
}

async function requestTranslations(
  apiKey: string,
  prompt: string
): Promise<FlatMessages> {
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "content-type": "application/json",
    },
    body: JSON.stringify({
      model: MODEL,
      max_tokens: 8192,
      messages: [{ role: "user", content: prompt }],
    }),
  });
  if (!response.ok) {
    throw new Error(
      `Anthropic API ${response.status}: ${await response.text()}`
    );
  }

  const payload: unknown = await response.json();
  const text =
    typeof payload === "object" &&
    payload !== null &&
    "content" in payload &&
    Array.isArray(payload.content) &&
    typeof payload.content[0] === "object" &&
    payload.content[0] !== null &&
    "text" in payload.content[0] &&
    typeof payload.content[0].text === "string"
      ? payload.content[0].text
      : null;
  if (text === null) {
    throw new Error("unexpected Anthropic API response shape");
  }

  const stripped = text
    .trim()
    .replace(/^```(?:json)?\n?/, "")
    .replace(/\n?```$/, "");
  const parsed: unknown = JSON.parse(stripped);
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("model reply is not a JSON object");
  }

  const translations: FlatMessages = {};
  for (const [key, value] of Object.entries(parsed)) {
    if (typeof value !== "string") {
      throw new Error(`model reply value for "${key}" is not a string`);
    }
    translations[key] = value;
  }
  return translations;
}

async function translateBatch(
  apiKey: string,
  locale: string,
  glossary: Glossary,
  batch: FlatMessages
): Promise<FlatMessages> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestTranslations(
        apiKey,
        buildPrompt(locale, glossary, batch)
      );
    } catch (error) {
      lastError = error;
      console.warn(
        `[${locale}] batch attempt ${attempt} failed: ${String(error)}`
      );
    }
  }
  throw lastError;
}

function chunk(keys: string[], size: number): string[][] {
  const chunks: string[][] = [];
  for (let start = 0; start < keys.length; start += size) {
    chunks.push(keys.slice(start, start + size));
  }
  return chunks;
}

async function main(): Promise<void> {
  const dryRun = process.argv.includes("--dry-run");

  const catalogs = loadCatalogs();
  const report = validateCatalogs(catalogs);
  if (report.errors.length > 0) {
    for (const issue of report.errors) {
      console.error(
        `${issue.locale ?? "meta"}:${issue.key} — ${issue.message}`
      );
    }
    console.error("Blocking catalog errors — fix these before translating.");
    process.exit(1);
  }

  const plan = planTranslationWork(catalogs);
  const workByLocale: Record<string, string[]> = {};
  for (const locale of TARGET_LOCALES) {
    const keys = new Set([...(plan.missing[locale] ?? []), ...plan.stale]);
    workByLocale[locale] = Array.from(keys).sort();
  }
  const totalWork = Object.values(workByLocale).reduce(
    (sum, keys) => sum + keys.length,
    0
  );

  if (totalWork === 0 && plan.orphanMetaKeys.length === 0) {
    console.log("Catalogs are complete and in sync. Nothing to translate.");
    return;
  }

  for (const [locale, keys] of Object.entries(workByLocale)) {
    console.log(`[${locale}] ${keys.length} key(s) to translate`);
    if (dryRun) {
      for (const key of keys) console.log(`  ${key}`);
    }
  }
  if (plan.orphanMetaKeys.length > 0) {
    console.log(`pruning ${plan.orphanMetaKeys.length} orphan meta entr(ies)`);
  }
  if (dryRun) return;

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (apiKey === undefined || apiKey === "") {
    console.error("ANTHROPIC_API_KEY is required (or pass --dry-run).");
    process.exit(1);
  }
  const glossary = readJsonFile<Glossary>(GLOSSARY_PATH);
  const englishTree = loadMessageTree(DEFAULT_LOCALE);

  // Keys that keep their previous stamp: a failed or rejected translation
  // must stay visible as missing/stale for the next run.
  const incompleteKeys = new Set<string>();

  for (const locale of TARGET_LOCALES) {
    const keys = workByLocale[locale] ?? [];
    if (keys.length === 0) continue;
    const catalog = catalogs.locales[locale];
    if (catalog === undefined) continue;

    for (const batchKeys of chunk(keys, BATCH_SIZE)) {
      const batch: FlatMessages = {};
      for (const key of batchKeys) {
        const source = catalogs.english[key];
        if (source !== undefined) batch[key] = source;
      }

      let translations: FlatMessages;
      try {
        translations = await translateBatch(apiKey, locale, glossary, batch);
      } catch {
        for (const key of batchKeys) incompleteKeys.add(key);
        console.error(
          `[${locale}] batch failed permanently; skipping ${batchKeys.length} key(s)`
        );
        continue;
      }

      for (const key of batchKeys) {
        const translation = translations[key];
        const source = catalogs.english[key];
        if (translation === undefined || source === undefined) {
          incompleteKeys.add(key);
          console.warn(`[${locale}] ${key}: no translation returned`);
          continue;
        }
        try {
          const parity =
            JSON.stringify(icuArguments(translation)) ===
            JSON.stringify(icuArguments(source));
          if (!parity) throw new Error("placeholder mismatch");
        } catch (error) {
          incompleteKeys.add(key);
          console.warn(`[${locale}] ${key}: rejected — ${String(error)}`);
          continue;
        }
        catalog[key] = translation;
      }
    }

    writeJsonFile(
      messagesPath(locale),
      toNestedInEnglishOrder(englishTree, catalog)
    );
    console.log(`[${locale}] wrote ${messagesPath(locale)}`);
  }

  writeJsonFile(META_PATH, buildStamp(catalogs, incompleteKeys));
  console.log(`stamped ${META_PATH}`);

  const finalReport = validateCatalogs(loadCatalogs());
  if (finalReport.errors.length > 0) {
    console.error("Post-translation validation failed — inspect the diff.");
    process.exit(1);
  }
  if (finalReport.warnings.length > 0) {
    console.warn(
      `${finalReport.warnings.length} advisory issue(s) remain for the next run.`
    );
  }
}

void main().catch((error: Error) => {
  console.error(String(error));
  process.exit(1);
});
