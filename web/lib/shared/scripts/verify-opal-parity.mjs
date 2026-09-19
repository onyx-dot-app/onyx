// Token parity gate — the no-regression guarantee for the Opal -> Shared token move.
//
// It proves that every design-token CSS variable resolves to the IDENTICAL concrete
// value (in BOTH light and dark) before and after the migration:
//
//   baseline  = Opal's token CSS on the PR BASE BRANCH (default origin/main), where
//               the pre-migration colors/sizes/z-index/typography.css still exist
//   new       = shared/dist/tokens.css  ∪  Opal's remaining src/styles/*.css
//
// The baseline is read from the base branch (NOT HEAD): on this PR, HEAD is already
// the migration commit (colors.css deleted), so reading HEAD would make the gate
// silently skip. Override the ref with PARITY_BASELINE_REF if needed.
//
// Asserts: same variable-name set, same resolved light value, same resolved dark
// value, and that no variable is defined in BOTH shared and opal (no duplication).
//
// Run:  node scripts/verify-opal-parity.mjs   (exits non-zero on any mismatch)

import { execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const sharedRoot = join(here, "..");
const repoRoot = join(sharedRoot, "..", "..", ".."); // web/lib/shared -> repo root
const OPAL_STYLES = "web/lib/opal/src/styles";
// The git ref holding the pre-migration baseline (the PR's base branch).
const BASELINE_REF = process.env.PARITY_BASELINE_REF || "origin/main";

const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, "");

// Parse a CSS string into { root: Map<name,rawValue>, dark: Map<name,rawValue> }.
function parse(css) {
  const text = stripComments(css);
  const root = new Map();
  const dark = new Map();
  const blockRe = /(:root|\.dark)\s*\{([^}]*)\}/g;
  let m;
  while ((m = blockRe.exec(text)) !== null) {
    const target = m[1] === ":root" ? root : dark;
    const declRe = /--([\w-]+)\s*:\s*([^;]+);/g;
    let d;
    while ((d = declRe.exec(m[2])) !== null) {
      target.set(d[1].trim(), d[2].trim().replace(/\s+/g, " "));
    }
  }
  return { root, dark };
}

const norm = (v) => String(v).toLowerCase().replace(/\s+/g, " ").trim();

// Resolve var() chains to a concrete value. `mode` is "light" or "dark".
function makeResolver(root, dark, mode) {
  const cache = new Map();
  const stack = new Set();
  function resolve(name) {
    const key = name;
    if (cache.has(key)) return cache.get(key);
    if (stack.has(key)) throw new Error(`cycle at --${name}`);
    stack.add(key);
    let raw =
      mode === "dark" && dark.has(name) ? dark.get(name) : root.get(name);
    if (raw === undefined) {
      stack.delete(key);
      return undefined;
    }
    const out = raw.replace(/var\(--([\w-]+)\)/g, (_, ref) => {
      const r = resolve(ref);
      return r === undefined ? `var(--${ref})` : r;
    });
    stack.delete(key);
    cache.set(key, out);
    return out;
  }
  return resolve;
}

function gitShow(path) {
  // Argument array (no shell) — `path` and the ref come only from constants/env.
  return execFileSync("git", ["show", `${BASELINE_REF}:${path}`], {
    cwd: repoRoot,
    encoding: "utf8",
    maxBuffer: 10 * 1024 * 1024,
  });
}

// ---- baseline (pre-migration Opal CSS on the base branch) ----
// Compares the new output against the pre-migration token CSS on BASELINE_REF. It is
// meaningful while the migration PR is open. Once merged, those files no longer exist
// on the base branch either, so `git show` exits 128 and the check skips cleanly.
// The baseline ref must actually resolve. git uses exit 128 for BOTH "file missing
// in ref" and "ref/repo missing", so check the ref up front: a missing ref (base
// branch not fetched in CI, wrong cwd, git absent) is an infra failure, not a
// legitimate post-migration skip — fail loudly so it can't masquerade as a pass.
function refExists(ref) {
  try {
    execFileSync(
      "git",
      ["rev-parse", "--verify", "--quiet", `${ref}^{commit}`],
      {
        cwd: repoRoot,
        stdio: ["ignore", "ignore", "ignore"],
      }
    );
    return true;
  } catch {
    return false;
  }
}
if (!refExists(BASELINE_REF)) {
  console.error(
    `FAIL: baseline ref '${BASELINE_REF}' not found — fetch it (e.g. git fetch origin main) or set PARITY_BASELINE_REF.`
  );
  process.exit(2);
}

let baseCss;
try {
  baseCss = ["colors.css", "sizes.css", "z-index.css", "typography.css"]
    .map((f) => gitShow(`${OPAL_STYLES}/${f}`))
    .join("\n");
} catch (err) {
  // The ref resolves (checked above), so an exit-128 here means the token files are
  // absent in it — the expected post-migration state once colors.css is deleted on
  // the base branch. Any other failure is unexpected and must fail loudly.
  if (err.status === 128) {
    console.log(
      `ℹ️  Opal token baseline not present on ${BASELINE_REF} (post-migration) — parity check skipped.`
    );
    process.exit(0);
  }
  console.error(
    `FAIL: could not read baseline from ${BASELINE_REF}:`,
    err.message
  );
  throw err;
}
const base = parse(baseCss);

// ---- new ----
const sharedTokens = join(sharedRoot, "dist", "tokens.css");
if (!existsSync(sharedTokens)) {
  console.error(
    `FAIL: ${sharedTokens} not found. Run \`bun run build:tokens\` first.`
  );
  process.exit(2);
}
const sharedParsed = parse(readFileSync(sharedTokens, "utf8"));

// Opal's remaining token-bearing styles (post-trim). Read whatever still exists.
const opalRemainingFiles = ["sizes.css", "z-index.css", "typography.css"];
let opalRoot = new Map();
let opalDark = new Map();
for (const f of opalRemainingFiles) {
  const p = join(repoRoot, OPAL_STYLES, f);
  if (!existsSync(p)) continue;
  const parsed = parse(readFileSync(p, "utf8"));
  for (const [k, v] of parsed.root) opalRoot.set(k, v);
  for (const [k, v] of parsed.dark) opalDark.set(k, v);
}

// Duplicate detection: a name must not be defined by BOTH shared and opal.
const duplicates = [...sharedParsed.root.keys()].filter((k) => opalRoot.has(k));

// Merge into the "new" universe.
const newRoot = new Map([...opalRoot, ...sharedParsed.root]);
const newDark = new Map([...opalDark, ...sharedParsed.dark]);

// ---- compare ----
const errors = [];

const baseRootNames = new Set(base.root.keys());
const newRootNames = new Set(newRoot.keys());
for (const n of baseRootNames)
  if (!newRootNames.has(n)) errors.push(`MISSING in new (:root): --${n}`);
for (const n of newRootNames)
  if (!baseRootNames.has(n)) errors.push(`EXTRA in new (:root): --${n}`);

const baseDarkNames = new Set(base.dark.keys());
const newDarkNames = new Set(newDark.keys());
for (const n of baseDarkNames)
  if (!newDarkNames.has(n)) errors.push(`MISSING in new (.dark): --${n}`);
for (const n of newDarkNames)
  if (!baseDarkNames.has(n)) errors.push(`EXTRA in new (.dark): --${n}`);

for (const d of duplicates)
  errors.push(
    `DUPLICATE: --${d} defined in BOTH shared/dist/tokens.css and opal src/styles`
  );

// Resolved-value comparison (light + dark) over the union of all root names.
const baseLight = makeResolver(base.root, base.dark, "light");
const baseDark = makeResolver(base.root, base.dark, "dark");
const newLight = makeResolver(newRoot, newDark, "light");
const newDark2 = makeResolver(newRoot, newDark, "dark");

for (const n of baseRootNames) {
  if (!newRootNames.has(n)) continue;
  const bl = baseLight(n),
    nl = newLight(n);
  if (norm(bl) !== norm(nl))
    errors.push(`LIGHT mismatch --${n}: base "${bl}" != new "${nl}"`);
  const bd = baseDark(n),
    nd = newDark2(n);
  if (norm(bd) !== norm(nd))
    errors.push(`DARK  mismatch --${n}: base "${bd}" != new "${nd}"`);
}

// ---- typography preset parity: @utility font-* blocks ----
// Parse `@utility font-NAME { prop: value; ... }` into { name: { prop: value } }.
function parseUtilities(css) {
  const text = stripComments(css);
  const out = {};
  const blockRe = /@utility\s+font-([\w-]+)\s*\{([^}]*)\}/g;
  let m;
  while ((m = blockRe.exec(text)) !== null) {
    const props = {};
    const declRe = /([\w-]+)\s*:\s*([^;]+);/g;
    let d;
    while ((d = declRe.exec(m[2])) !== null) {
      props[d[1].trim()] = d[2].trim().replace(/\s+/g, " ");
    }
    out[m[1]] = props;
  }
  return out;
}

const baseUtils = parseUtilities(baseCss);
const genTypoPath = join(sharedRoot, "dist", "typography.css");
if (!existsSync(genTypoPath)) {
  errors.push(
    "MISSING dist/typography.css — run `bun run build:tokens` first."
  );
} else {
  const genUtils = parseUtilities(readFileSync(genTypoPath, "utf8"));
  const baseNames = new Set(Object.keys(baseUtils));
  const genNames = new Set(Object.keys(genUtils));
  for (const n of baseNames)
    if (!genNames.has(n))
      errors.push(`MISSING @utility font-${n} in generated typography.css`);
  for (const n of genNames)
    if (!baseNames.has(n))
      errors.push(`EXTRA @utility font-${n} in generated typography.css`);
  for (const n of baseNames) {
    if (!genNames.has(n)) continue;
    const a = baseUtils[n],
      b = genUtils[n];
    const props = new Set([...Object.keys(a), ...Object.keys(b)]);
    for (const p of props) {
      if (norm(a[p] ?? "") !== norm(b[p] ?? ""))
        errors.push(
          `TYPO mismatch font-${n}.${p}: base "${a[p]}" != new "${b[p]}"`
        );
    }
  }
}

// ---- report ----
if (errors.length) {
  console.error(`\n❌ Token parity FAILED — ${errors.length} issue(s):\n`);
  for (const e of errors.slice(0, 100)) console.error("  - " + e);
  if (errors.length > 100)
    console.error(`  ... and ${errors.length - 100} more`);
  process.exit(1);
}
console.log(
  `✅ Token parity OK — ${baseRootNames.size} :root vars and ${baseDarkNames.size} .dark vars ` +
    `resolve identically (light + dark), ${Object.keys(baseUtils).length} typography ` +
    `@utility presets match, no duplicates.`
);
