/**
 * Validate the i18n message catalogs.
 *
 *   bun run i18n:check           # exit 1 on any catalog error
 *   bun scripts/i18n/check.ts --update
 *
 * The blocking contract for authors: every en.json key has a translation in
 * every locale, every message is valid ICU, and placeholders match English.
 * Runs in pre-commit (on web/src/i18n/ changes) and via the Jest catalog
 * test in CI.
 *
 * `--update` rewrites `src/i18n/catalog.meta.json`, which records the English
 * source each key was last QA-reviewed against. The weekly QA pipeline owns
 * that file; the flag exists for the pipeline itself and for re-baselining
 * after a manual review — not for regular authoring.
 */
import {
  buildStamp,
  planTranslationWork,
  validateCatalogs,
  type CatalogIssue,
} from "@/i18n/validation";
import { loadCatalogs, META_PATH, writeJsonFile } from "./shared";

function printIssues(label: string, issues: CatalogIssue[]): void {
  if (issues.length === 0) return;
  console.log(`${label} (${issues.length}):`);
  for (const issue of issues) {
    const scope = issue.locale ? `${issue.locale}:${issue.key}` : issue.key;
    console.log(`  ${scope} — ${issue.message}`);
  }
}

function main(): void {
  const update = process.argv.includes("--update");

  const catalogs = loadCatalogs();
  const report = validateCatalogs(catalogs);
  printIssues("Errors", report.errors);
  if (report.errors.length > 0) {
    console.error(
      "Catalog errors — translate every key you touch in every locale " +
        "(see web/AGENTS.md §7)."
    );
    process.exit(1);
  }

  if (update) {
    const stamp = buildStamp(catalogs);
    writeJsonFile(META_PATH, stamp);
    console.log(`Stamped ${Object.keys(stamp).length} key(s) → ${META_PATH}`);
    return;
  }

  const plan = planTranslationWork(catalogs);
  const pending =
    plan.stale.length + plan.unreviewed.length + plan.orphanMetaKeys.length;
  if (pending > 0) {
    console.log(
      `Catalogs are valid. Awaiting weekly QA: ${plan.unreviewed.length} ` +
        `new, ${plan.stale.length} changed, ${plan.orphanMetaKeys.length} ` +
        `removed key(s).`
    );
  } else {
    console.log("Catalogs are valid and fully QA-reviewed.");
  }
}

main();
