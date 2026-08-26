/**
 * Weekly QA reviewer for the message catalogs.
 *
 * Authors hand-translate every key they touch, and CI blocks on key parity
 * (web/AGENTS.md §7). This script is the quality pass behind that: it sends
 * new keys (never reviewed) and changed keys (English source differs from the
 * last review, per `catalog.meta.json`) to Claude, which keeps acceptable
 * translations as-is and corrects genuine defects. Missing translations —
 * possible only outside the normal PR flow — are filled the same way. The
 * i18n-qa workflow runs this weekly and opens a reviewed PR with the result.
 *
 *   ANTHROPIC_API_KEY=... bun run i18n:qa
 *   bun run i18n:qa -- --dry-run   # print the review list, no API calls
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
const MODEL = process.env.ONYX_I18N_QA_MODEL ?? "claude-sonnet-5";

interface ReviewItem {
  source: string;
  translation: string | null;
}

type ReviewBatch = Record<string, ReviewItem>;

function buildPrompt(
  locale: string,
  glossary: Glossary,
  batch: ReviewBatch
): string {
  const termLines = Object.entries(glossary.terms)
    .map(([term, byLocale]) => {
      const translation = byLocale[locale];
      return translation === undefined ? null : `"${term}" → "${translation}"`;
    })
    .filter((line): line is string => line !== null);

  return [
    "You are QA-reviewing UI translations for Onyx, an enterprise AI search and chat product.",
    "",
    `Target locale: "${locale}". ${glossary.localeStyle[locale] ?? ""}`,
    "",
    "Each key maps to the English `source` and the current `translation` (null if none exists yet).",
    "",
    "Rules:",
    "- Return the final translation for every key. Keep the existing translation verbatim unless it has a genuine defect: meaning that no longer matches the source, wrong register, a glossary violation, or broken ICU. Do not restyle acceptable translations.",
    "- If `translation` is null, translate the source.",
    "- Messages are ICU MessageFormat. Keep every {argument} name, plural/select structure, and <tag></tag> name exactly as in the source; translate only the human-readable text.",
    `- Keep brand and product names in English (LinkedIn, YouTube, Slack, ${glossary.doNotTranslate.join(", ")}, ...).`,
    ...(termLines.length > 0
      ? [`- Glossary, use these exact translations: ${termLines.join("; ")}`]
      : []),
    "- Keys are stable identifiers whose dot-path hints at the UI context (namespace.section.element.role). Never alter keys.",
    "- Match the tone and brevity of product UI copy.",
    "",
    "Review this JSON object:",
    JSON.stringify(batch, null, 2),
    "",
    "Reply with only a JSON object mapping every input key to its final translation string.",
  ].join("\n");
}

async function requestReview(
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

async function reviewBatch(
  apiKey: string,
  locale: string,
  glossary: Glossary,
  batch: ReviewBatch
): Promise<FlatMessages> {
  let lastError: unknown;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      return await requestReview(apiKey, buildPrompt(locale, glossary, batch));
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
      console.error(`${issue.locale ?? "en"}:${issue.key} — ${issue.message}`);
    }
    console.error("Blocking catalog errors — fix these before running QA.");
    process.exit(1);
  }

  const plan = planTranslationWork(catalogs);
  const reviewKeys = Array.from(
    new Set([...plan.stale, ...plan.unreviewed])
  ).sort();
  const workByLocale: Record<string, string[]> = {};
  for (const locale of TARGET_LOCALES) {
    const keys = new Set([...(plan.missing[locale] ?? []), ...reviewKeys]);
    workByLocale[locale] = Array.from(keys).sort();
  }
  const totalWork = Object.values(workByLocale).reduce(
    (sum, keys) => sum + keys.length,
    0
  );

  if (totalWork === 0 && plan.orphanMetaKeys.length === 0) {
    console.log("Catalogs are fully QA-reviewed. Nothing to do.");
    return;
  }

  console.log(
    `${plan.unreviewed.length} new and ${plan.stale.length} changed key(s) to review`
  );
  if (plan.orphanMetaKeys.length > 0) {
    console.log(`pruning ${plan.orphanMetaKeys.length} orphan meta entr(ies)`);
  }
  if (dryRun) {
    for (const [locale, keys] of Object.entries(workByLocale)) {
      console.log(`[${locale}] ${keys.length} key(s):`);
      for (const key of keys) console.log(`  ${key}`);
    }
    return;
  }

  const apiKey = process.env.ANTHROPIC_API_KEY;
  if (apiKey === undefined || apiKey === "") {
    console.error("ANTHROPIC_API_KEY is required (or pass --dry-run).");
    process.exit(1);
  }
  const glossary = readJsonFile<Glossary>(GLOSSARY_PATH);
  const englishTree = loadMessageTree(DEFAULT_LOCALE);

  // Keys that keep their previous meta entry: a failed or rejected review
  // must stay visible as new/changed for the next run.
  const incompleteKeys = new Set<string>();
  let corrected = 0;
  let kept = 0;

  for (const locale of TARGET_LOCALES) {
    const keys = workByLocale[locale] ?? [];
    if (keys.length === 0) continue;
    const catalog = catalogs.locales[locale];
    if (catalog === undefined) continue;

    for (const batchKeys of chunk(keys, BATCH_SIZE)) {
      const batch: ReviewBatch = {};
      for (const key of batchKeys) {
        const source = catalogs.english[key];
        if (source !== undefined) {
          batch[key] = { source, translation: catalog[key] ?? null };
        }
      }

      let reviewed: FlatMessages;
      try {
        reviewed = await reviewBatch(apiKey, locale, glossary, batch);
      } catch {
        for (const key of batchKeys) incompleteKeys.add(key);
        console.error(
          `[${locale}] batch failed permanently; skipping ${batchKeys.length} key(s)`
        );
        continue;
      }

      for (const key of batchKeys) {
        const final = reviewed[key];
        const source = catalogs.english[key];
        if (final === undefined || source === undefined) {
          incompleteKeys.add(key);
          console.warn(`[${locale}] ${key}: no reply for this key`);
          continue;
        }
        try {
          const parity =
            JSON.stringify(icuArguments(final)) ===
            JSON.stringify(icuArguments(source));
          if (!parity) throw new Error("placeholder mismatch");
        } catch (error) {
          incompleteKeys.add(key);
          console.warn(`[${locale}] ${key}: rejected — ${String(error)}`);
          continue;
        }
        if (catalog[key] === final) {
          kept += 1;
        } else {
          corrected += 1;
          console.log(`[${locale}] ${key}: corrected`);
        }
        catalog[key] = final;
      }
    }

    writeJsonFile(
      messagesPath(locale),
      toNestedInEnglishOrder(englishTree, catalog)
    );
  }

  writeJsonFile(META_PATH, buildStamp(catalogs, incompleteKeys));
  console.log(
    `QA complete: ${kept} kept, ${corrected} corrected, ` +
      `${incompleteKeys.size} deferred to the next run. Stamped ${META_PATH}.`
  );

  const finalReport = validateCatalogs(loadCatalogs());
  if (finalReport.errors.length > 0) {
    console.error("Post-QA validation failed — inspect the diff.");
    process.exit(1);
  }
}

void main().catch((error: Error) => {
  console.error(String(error));
  process.exit(1);
});
