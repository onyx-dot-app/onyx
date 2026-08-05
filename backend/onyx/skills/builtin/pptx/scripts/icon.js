#!/usr/bin/env node
// Render an SVG icon (lucide-static or @tabler/icons) to a recolored PNG for
// slide decks.
//
// Render:  node icon.js circle-check --color 1E2761 --size 512 -o outputs/icons/check.png
// Search:  node icon.js --list "shield" [--set lucide|tabler]
//
// Deps (lucide-static, @tabler/icons, sharp) are baked into the sandbox image
// as global npm packages; this script resolves them from the global npm root
// since NODE_PATH is not set in the sandbox.
"use strict";

const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const DEFAULT_SIZE = 512;
const DEFAULT_COLOR = "000000";
const MAX_LIST_RESULTS = 60;
const MAX_SUGGESTIONS = 8;
const SVG_NATIVE_SIZE = 24; // both packages ship 24x24 viewBox SVGs

const MISSING_DEPS_MESSAGE = `Error: icon rendering dependencies (lucide-static, @tabler/icons, sharp) are missing from this sandbox image.`;

function fail(message) {
  process.stderr.write(message + "\n");
  process.exit(1);
}

function globalNpmRoot() {
  try {
    return execFileSync("npm", ["root", "-g"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
  } catch {
    return null;
  }
}

const _resolvePaths = [...module.paths, "/usr/local/lib/node_modules"];
let _npmRootAdded = false;

function resolvePaths() {
  if (!_npmRootAdded) {
    const root = globalNpmRoot();
    if (root && !_resolvePaths.includes(root)) _resolvePaths.push(root);
    _npmRootAdded = true;
  }
  return _resolvePaths;
}

// Locate an installed package's root directory by scanning the resolve paths
// (each entry is a node_modules dir). Deliberately avoids require.resolve:
// @tabler/icons only exports "./*" -> "./icons/*", which hides package.json.
function packageDir(packageName) {
  for (const base of resolvePaths()) {
    const candidate = path.join(base, ...packageName.split("/"));
    if (fs.existsSync(path.join(candidate, "package.json"))) return candidate;
  }
  return null;
}

function loadSharp() {
  let resolved;
  try {
    resolved = require.resolve("sharp", { paths: resolvePaths() });
  } catch (err) {
    if (err && err.code === "MODULE_NOT_FOUND") fail(MISSING_DEPS_MESSAGE);
    throw err;
  }
  try {
    return require(resolved);
  } catch (err) {
    fail(`${MISSING_DEPS_MESSAGE}\n\n(underlying error loading "sharp": ${err.message.split("\n")[0]})`);
  }
}

// Each icon "set" is a label plus the directories its .svg files live in,
// searched in order (tabler: outline first, then filled).
function iconSets() {
  const sets = [];
  const lucideRoot = packageDir("lucide-static");
  if (lucideRoot) sets.push({ name: "lucide", dirs: [path.join(lucideRoot, "icons")] });
  const tablerRoot = packageDir("@tabler/icons");
  if (tablerRoot) {
    sets.push({
      name: "tabler",
      dirs: [path.join(tablerRoot, "icons", "outline"), path.join(tablerRoot, "icons", "filled")],
    });
  }
  if (sets.length === 0) fail(MISSING_DEPS_MESSAGE);
  return sets;
}

function scopeSets(sets, setArg) {
  if (!setArg) return sets;
  const wanted = setArg.toLowerCase();
  const scoped = sets.filter((s) => s.name === wanted);
  if (scoped.length === 0) fail(`Error: unknown icon set "${setArg}". Available sets: lucide, tabler.`);
  return scoped;
}

function iconNamesOf(set) {
  const names = new Set();
  for (const dir of set.dirs) {
    let entries;
    try {
      entries = fs.readdirSync(dir);
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (entry.endsWith(".svg")) names.add(entry.slice(0, -4));
    }
  }
  return [...names];
}

function findIconFile(sets, iconName) {
  for (const set of sets) {
    for (const dir of set.dirs) {
      const file = path.join(dir, `${iconName}.svg`);
      if (fs.existsSync(file)) return file;
    }
  }
  return null;
}

function levenshtein(a, b) {
  const m = a.length;
  const n = b.length;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[n];
}

function suggestClose(target, candidates) {
  const lowerTarget = target.toLowerCase();
  return [...new Set(candidates)]
    .map((c) => {
      const isSubstring = c.includes(lowerTarget) || lowerTarget.includes(c);
      return [levenshtein(lowerTarget, c) - (isSubstring ? 2 : 0), c];
    })
    .sort((a, b) => a[0] - b[0] || a[1].localeCompare(b[1]))
    .slice(0, MAX_SUGGESTIONS)
    .map(([, c]) => c);
}

function runList(query, setArg) {
  const sets = scopeSets(iconSets(), setArg);
  const lowerQuery = query.toLowerCase();
  const matches = [];
  for (const set of sets) {
    for (const name of iconNamesOf(set).sort()) {
      if (name.includes(lowerQuery)) matches.push(`${name}  (${set.name})`);
    }
  }
  if (matches.length === 0) {
    fail(
      `No icons matching "${query}" in ${sets.map((s) => s.name).join(", ")}.\n` +
        `Try a shorter/simpler query (e.g. "chart" not "growth chart"), or the other set with --set.`
    );
  }
  process.stdout.write(matches.slice(0, MAX_LIST_RESULTS).join("\n") + "\n");
  if (matches.length > MAX_LIST_RESULTS) {
    process.stdout.write(`... ${matches.length - MAX_LIST_RESULTS} more matches truncated; refine the query\n`);
  }
}

function normalizeColor(raw) {
  const m = /^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$/.exec(raw);
  if (!m) fail(`Error: --color must be a 3- or 6-digit hex color (got "${raw}").`);
  let hex = m[1];
  if (hex.length === 3) hex = hex.split("").map((c) => c + c).join("");
  return "#" + hex.toUpperCase();
}

async function runRender(iconName, opts) {
  const sharp = loadSharp();
  const sets = scopeSets(iconSets(), opts.set);

  const file = findIconFile(sets, iconName);
  if (!file) {
    const allNames = sets.flatMap((s) => iconNamesOf(s));
    const suggestions = suggestClose(iconName, allNames);
    fail(
      `Error: icon "${iconName}" not found in ${sets.map((s) => s.name).join(", ")}.\n` +
        `Names are kebab-case (e.g. circle-check, trending-up).\n` +
        `Close matches:\n  ${suggestions.join("\n  ")}\n` +
        `Or search by keyword: node icon.js --list "<keyword>"`
    );
  }

  // Both sets draw with stroke/fill="currentColor"; substitute the literal hex.
  const svg = fs.readFileSync(file, "utf8").replace(/currentColor/g, opts.color);

  const outPath = opts.out || path.join("outputs", "icons", `${iconName}.png`);
  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  // density scales SVG rasterization so the icon renders vector-crisp at the
  // target size instead of being upscaled from 24px.
  const density = (72 * opts.size) / SVG_NATIVE_SIZE;
  const png = await sharp(Buffer.from(svg), { density }).resize(opts.size, opts.size).png().toBuffer();
  fs.writeFileSync(outPath, png);
  process.stdout.write(`Wrote ${outPath} (${opts.size}x${opts.size}px, ${opts.color})\n`);
}

const USAGE = `Usage:
  node icon.js <icon-name> [--color <hex>] [--size <px>] [-o <out.png>] [--set lucide|tabler]
  node icon.js --list "<query>" [--set lucide|tabler]

Options:
  --color, -c   Hex color, with or without '#' (default ${DEFAULT_COLOR})
  --size, -s    Raster size in pixels, 16-2048 (default ${DEFAULT_SIZE})
  --out, -o     Output PNG path (default outputs/icons/<icon-name>.png)
  --list        Fuzzy-search icon names by keyword instead of rendering
  --set         Restrict lookup/search to one set (lucide or tabler)

Icon names are kebab-case file names, e.g. circle-check, trending-up, shield-check.

Examples:
  node icon.js circle-check --color 1E2761 -o outputs/icons/check.png
  node icon.js --list "shield" --set tabler`;

function parseArgs(argv) {
  const opts = {
    iconName: null,
    color: DEFAULT_COLOR,
    size: DEFAULT_SIZE,
    out: null,
    list: null,
    set: null,
  };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => {
      i++;
      if (i >= argv.length) fail(`Error: ${arg} requires a value.\n\n${USAGE}`);
      return argv[i];
    };
    if (arg === "--help" || arg === "-h") {
      process.stdout.write(USAGE + "\n");
      process.exit(0);
    } else if (arg === "--color" || arg === "-c") opts.color = next();
    else if (arg === "--size" || arg === "-s") opts.size = next();
    else if (arg === "--out" || arg === "-o") opts.out = next();
    else if (arg === "--list") opts.list = next();
    else if (arg === "--set") opts.set = next();
    else if (arg.startsWith("--")) fail(`Error: unknown option "${arg}".\n\n${USAGE}`);
    else if (opts.iconName === null) opts.iconName = arg;
    else fail(`Error: unexpected extra argument "${arg}".\n\n${USAGE}`);
  }
  return opts;
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (opts.list !== null) {
    runList(opts.list, opts.set);
    return;
  }
  if (!opts.iconName) fail(USAGE);
  opts.color = normalizeColor(opts.color);
  opts.size = Number(String(opts.size).trim());
  if (!Number.isInteger(opts.size) || opts.size < 16 || opts.size > 2048) {
    fail("Error: --size must be an integer between 16 and 2048.");
  }
  await runRender(opts.iconName, opts);
}

main().catch((err) => fail(`Error: ${err.message}`));
