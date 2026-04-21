import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import type { AxeResults, Result as AxeViolation } from "axe-core";

/**
 * WCAG tag sets used to scope axe-core analysis.
 *
 * "wcag-aa" targets WCAG 2.1 Level AA — the standard compliance bar for most
 * products. "wcag-aaa" adds Level AAA rules for stricter audits. "all" runs
 * every rule axe-core ships, including best-practice checks that aren't part
 * of any WCAG success criterion.
 */
export type WcagLevel = "wcag-aa" | "wcag-aaa" | "all";

const WCAG_TAGS: Record<WcagLevel, string[]> = {
  "wcag-aa": ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
  "wcag-aaa": [
    "wcag2a",
    "wcag2aa",
    "wcag2aaa",
    "wcag21a",
    "wcag21aa",
    "wcag21aaa",
  ],
  all: [],
};

/**
 * Rules that have been fixed and MUST NOT regress. Violations of these rules
 * will fail the test. All other rules are reported as warnings only.
 *
 * Workflow: fix all instances of a rule across the app, then move the rule ID
 * here so CI prevents regressions. This is the ratchet — it only tightens.
 */
export const STRICT_RULES: string[] = [
  // Add rule IDs here as they are fixed, e.g.:
  // "button-name",
  // "image-alt",
];

export interface A11yScanOptions {
  /** CSS selectors to include in the scan. Defaults to the full page. */
  include?: string[];
  /** CSS selectors to exclude from the scan. */
  exclude?: string[];
  /** Rule IDs to disable for this scan. */
  disableRules?: string[];
  /** WCAG conformance level. Defaults to "wcag-aa". */
  level?: WcagLevel;
}

/**
 * Run an axe-core accessibility scan against the current page state and return
 * the raw results. Use this when you need programmatic access to violations
 * (e.g. to generate reports or filter results). For simple pass/fail
 * assertions, prefer {@link expectAccessible} via the fixture.
 */
export async function scanAccessibility(
  page: Page,
  options: A11yScanOptions = {}
): Promise<AxeResults> {
  const { include, exclude, disableRules, level = "wcag-aa" } = options;

  let builder = new AxeBuilder({ page });

  const tags = WCAG_TAGS[level];
  if (tags.length > 0) {
    builder = builder.withTags(tags);
  }

  if (include) {
    for (const selector of include) {
      builder = builder.include(selector);
    }
  }
  if (exclude) {
    for (const selector of exclude) {
      builder = builder.exclude(selector);
    }
  }
  if (disableRules) {
    builder = builder.disableRules(disableRules);
  }

  return builder.analyze();
}

/**
 * Split violations into strict (must fail) and warnings (report only).
 */
export function partitionViolations(violations: AxeViolation[]): {
  strict: AxeViolation[];
  warnings: AxeViolation[];
} {
  const strictSet = new Set(STRICT_RULES);
  const strict: AxeViolation[] = [];
  const warnings: AxeViolation[] = [];

  for (const v of violations) {
    if (strictSet.has(v.id)) {
      strict.push(v);
    } else {
      warnings.push(v);
    }
  }

  return { strict, warnings };
}

/**
 * Format a single axe violation into a human-readable string.
 */
function formatViolation(v: AxeViolation): string {
  const nodes = v.nodes
    .slice(0, 5)
    .map((n) => `    ${n.target.join(" > ")}`)
    .join("\n");

  const truncated =
    v.nodes.length > 5 ? `\n    ... and ${v.nodes.length - 5} more` : "";

  return [
    `  [${v.impact?.toUpperCase()}] ${v.id}: ${v.help} (${
      v.nodes.length
    } nodes)`,
    `  ${v.helpUrl}`,
    nodes + truncated,
  ].join("\n");
}

/**
 * Format violations for assertion failure messages.
 */
export function formatViolations(violations: AxeViolation[]): string {
  if (violations.length === 0) return "No accessibility violations found.";

  const header = `${violations.length} accessibility violation(s):\n`;
  return header + violations.map(formatViolation).join("\n\n");
}

/**
 * Format violations as a compact warning summary for test annotations.
 */
export function formatWarnings(violations: AxeViolation[]): string {
  if (violations.length === 0) return "";

  return violations
    .map(
      (v) =>
        `[${v.impact?.toUpperCase()}] ${v.id}: ${v.help} (${
          v.nodes.length
        } nodes)`
    )
    .join("\n");
}
