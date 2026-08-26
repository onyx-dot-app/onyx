/**
 * Validate the i18n message catalogs, and stamp the staleness meta.
 *
 *   bun run i18n:check          # report; exit 1 on blocking errors
 *   bun run i18n:check --strict # also exit 1 on warnings (CI for the bot PR)
 *   bun run i18n:stamp          # rewrite src/i18n/catalog.meta.json
 *
 * Stamping records the hash of the English source each key's translations are
 * in sync with. Run it after you translate — never to silence a stale warning
 * you have not actually fixed.
 */
import {
  buildStamp,
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
  const strict = process.argv.includes("--strict");

  const catalogs = loadCatalogs();
  const report = validateCatalogs(catalogs);

  printIssues("Errors", report.errors);
  printIssues("Warnings", report.warnings);

  if (report.errors.length > 0) {
    console.error(
      "Blocking catalog errors — fix these before stamping or translating."
    );
    process.exit(1);
  }

  if (update) {
    const stamp = buildStamp(catalogs);
    writeJsonFile(META_PATH, stamp);
    console.log(`Stamped ${Object.keys(stamp).length} key(s) → ${META_PATH}`);
    return;
  }

  if (strict && report.warnings.length > 0) {
    console.error("Warnings present and --strict was given.");
    process.exit(1);
  }

  if (report.warnings.length === 0) {
    console.log("Catalogs are complete and in sync.");
  }
}

main();
