import { readFileSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { join, relative, resolve } from "node:path";

/** A CSS class, custom property, or design token that nothing references. */
export interface CssFinding {
  readonly kind: "class" | "property" | "token";
  readonly name: string;
  readonly file: string;
  readonly line: number;
}

export interface CssCheckOptions {
  /** Absolute path to web/. */
  readonly webRoot: string;
  /**
   * Extra directories to scan for usage. mobile/ belongs here: it consumes the
   * shared design tokens through NativeWind, and nothing inside web/ records
   * that.
   */
  readonly extraCorpusRoots: readonly string[];
  /**
   * Names that are always live. Each entry needs a comment saying why, because
   * an entry here is a permanent exemption rather than a baseline.
   */
  readonly ignore: readonly string[];
}

interface Definition {
  readonly name: string;
  readonly file: string;
  readonly line: number;
}

const SOURCE_EXTENSIONS = [".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"];
const SKIP_DIRECTORIES = new Set([
  "node_modules",
  "dist",
  ".next",
  ".git",
  "coverage",
  "storybook-static",
  "android",
  "ios",
  ".expo",
]);

async function collectFiles(
  root: string,
  accept: (path: string) => boolean
): Promise<string[]> {
  const found: string[] = [];
  async function walk(directory: string): Promise<void> {
    let entries;
    try {
      entries = await readdir(directory, { withFileTypes: true });
    } catch {
      return;
    }
    for (const entry of entries) {
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        if (SKIP_DIRECTORIES.has(entry.name)) continue;
        await walk(path);
      } else if (entry.isFile() && accept(path)) {
        found.push(path);
      }
    }
  }
  await walk(root);
  return found;
}

function read(path: string): string {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

/**
 * Remove the left-hand side of every custom-property declaration. A token is
 * declared in the generated lib/shared/dist/tokens.css as well as authored in
 * tokens/*.json; without this, every token would look like it references
 * itself and nothing would ever be reported.
 */
function stripPropertyDeclarations(css: string): string {
  return css.replace(/(^|[;{])(\s*)--[\w-]+(\s*):/g, "$1$2$3:");
}

/** Drop comments so a name mentioned in prose never counts as a reference. */
function stripCssComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

function lineOf(text: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index; i++) {
    if (text[i] === "\n") line++;
  }
  return line;
}

/**
 * Class selectors, read from selector position only. Taking the text before
 * each `{` keeps `.foo` in `content: ".foo"` out of the definition set.
 */
function collectClassDefinitions(
  css: string,
  file: string
): Map<string, Definition> {
  const definitions = new Map<string, Definition>();
  const stripped = stripCssComments(css);
  const blocks = /(^|[};])([^{};]*)\{/g;
  let block: RegExpExecArray | null;
  while ((block = blocks.exec(stripped)) !== null) {
    const selector = block[2];
    if (selector.trimStart().startsWith("@")) continue;
    const selectorStart = block.index + block[1].length;
    const classes = /\.(-?[A-Za-z_][\w-]*)/g;
    let match: RegExpExecArray | null;
    while ((match = classes.exec(selector)) !== null) {
      const name = match[1];
      if (definitions.has(name)) continue;
      definitions.set(name, {
        name,
        file,
        line: lineOf(stripped, selectorStart + match.index),
      });
    }
  }
  return definitions;
}

/** Custom properties, declared as `--name:` at the start of a declaration. */
function collectPropertyDefinitions(
  css: string,
  file: string
): Map<string, Definition> {
  const definitions = new Map<string, Definition>();
  const stripped = stripCssComments(css);
  const declarations = /(?:^|[;{])\s*(--[\w-]+)\s*:/g;
  let match: RegExpExecArray | null;
  while ((match = declarations.exec(stripped)) !== null) {
    const name = match[1];
    if (definitions.has(name)) continue;
    definitions.set(name, { name, file, line: lineOf(stripped, match.index) });
  }
  return definitions;
}

interface TokenSet {
  /** Leaf name -> where it is declared. The leaf name is the CSS var name. */
  readonly definitions: Map<string, Definition>;
  /** Leaf names that another token's authored value references as `{ref}`. */
  readonly aliased: Set<string>;
}

/**
 * Walk the token JSON. Per lib/shared/style-dictionary.config.mjs, the last
 * path segment of every leaf is the CSS variable name verbatim, and a value of
 * `{some-other-token}` compiles to `var(--some-other-token)`.
 */
function collectTokens(files: readonly string[], webRoot: string): TokenSet {
  const definitions = new Map<string, Definition>();
  const aliased = new Set<string>();

  for (const file of files) {
    const raw = read(file);
    const relativePath = relative(webRoot, file);
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      continue;
    }

    // Deliberately narrow: `[^}]+` would run across the JSON's own nested
    // braces and capture a whole object instead of the reference.
    const references = /\{([A-Za-z0-9_.-]+)\}/g;
    let reference: RegExpExecArray | null;
    while ((reference = references.exec(raw)) !== null) {
      const segments = reference[1].split(".");
      aliased.add(segments[segments.length - 1]);
    }

    function walk(node: unknown, path: readonly string[]): void {
      if (node === null || typeof node !== "object") return;
      const record = node as Record<string, unknown>;
      const isLeaf = "value" in record || "$value" in record;
      if (isLeaf) {
        const name = path[path.length - 1];
        if (name !== undefined && !definitions.has(name)) {
          const declaration = raw.indexOf(`"${name}"`);
          definitions.set(name, {
            name,
            file: relativePath,
            line: declaration === -1 ? 1 : lineOf(raw, declaration),
          });
        }
        return;
      }
      for (const [key, child] of Object.entries(record)) {
        walk(child, [...path, key]);
      }
    }

    walk(parsed, []);
  }

  return { definitions, aliased };
}

/**
 * Every string literal in the source corpus, used to keep a dynamically built
 * class name such as `cn("tag-" + tone)` out of the findings.
 */
function collectStringLiterals(sources: readonly string[]): string[] {
  const literals = new Set<string>();
  const pattern = /["'`]([^"'`\n]{2,80})["'`]/g;
  for (const source of sources) {
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(source)) !== null) {
      literals.add(match[1]);
    }
  }
  return [...literals];
}

/**
 * Whether a custom property is referenced. `\b` cannot lead a match for a name
 * that starts with `--`, because a hyphen is not a word character. That would
 * miss Tailwind v4's arbitrary-property syntax, `max-w-(--app-container-sm)`,
 * which is how most of these are actually used.
 */
function referencesProperty(haystack: string, name: string): boolean {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`${escaped}(?![\\w-])`).test(haystack);
}

function wordBoundaryCount(haystack: string, needle: string): number {
  const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const matches = haystack.match(new RegExp(`\\b${escaped}\\b`, "g"));
  return matches === null ? 0 : matches.length;
}

export async function findDeadCss(
  options: CssCheckOptions
): Promise<CssFinding[]> {
  const { webRoot, extraCorpusRoots, ignore } = options;
  const opalSource = resolve(webRoot, "lib/opal/src");
  const ignored = new Set(ignore);

  // Definition sites: the design system's own stylesheets, plus the app's.
  const cssFiles = (
    await Promise.all(
      [opalSource, resolve(webRoot, "src")].map((root) =>
        collectFiles(root, (path) => path.endsWith(".css"))
      )
    )
  ).flat();

  // Usage corpus: every stylesheet that can reference a definition, including
  // the generated token CSS, which resolves one token against another.
  const cssCorpusFiles = [
    ...cssFiles,
    ...(await collectFiles(resolve(webRoot, "tailwind-themes"), (path) =>
      path.endsWith(".css")
    )),
    ...(await collectFiles(resolve(webRoot, "lib/shared/dist"), (path) =>
      path.endsWith(".css")
    )),
  ];
  const tokenFiles = await collectFiles(
    resolve(webRoot, "lib/shared/tokens"),
    (path) => path.endsWith(".json")
  );

  const sourceRoots = [
    resolve(webRoot, "src"),
    opalSource,
    resolve(webRoot, "lib/shared/src"),
    resolve(webRoot, "tailwind-themes"),
    ...extraCorpusRoots,
  ];
  const sourceFiles = (
    await Promise.all(
      sourceRoots.map((root) =>
        collectFiles(root, (path) =>
          SOURCE_EXTENSIONS.some((extension) => path.endsWith(extension))
        )
      )
    )
  ).flat();
  sourceFiles.push(resolve(webRoot, "lib/opal/tailwind-preset.cjs"));

  const sources = sourceFiles.map(read);
  const sourceBlob = sources.join("\n");
  const cssBlob = cssCorpusFiles
    .map((file) => stripCssComments(read(file)))
    .join("\n");
  // Used when asking whether a custom property or token is *referenced*, where
  // its own declaration must not count.
  const cssReferenceBlob = stripPropertyDeclarations(cssBlob);
  const literals = collectStringLiterals(sources);

  const classDefinitions = new Map<string, Definition>();
  const propertyDefinitions = new Map<string, Definition>();
  for (const file of cssFiles) {
    const css = read(file);
    const relativePath = relative(webRoot, file);
    for (const [name, definition] of collectClassDefinitions(
      css,
      relativePath
    )) {
      if (!classDefinitions.has(name)) classDefinitions.set(name, definition);
    }
    for (const [name, definition] of collectPropertyDefinitions(
      css,
      relativePath
    )) {
      if (!propertyDefinitions.has(name)) {
        propertyDefinitions.set(name, definition);
      }
    }
  }

  const findings: CssFinding[] = [];

  for (const [name, definition] of classDefinitions) {
    if (ignored.has(name)) continue;
    if (wordBoundaryCount(sourceBlob, name) > 0) continue;
    // A reference from another rule counts, so compare against the number of
    // selector positions that declare the class rather than against zero.
    const declarations = cssFiles.filter((file) =>
      collectClassDefinitions(read(file), file).has(name)
    ).length;
    if (wordBoundaryCount(cssBlob, name) > declarations) continue;
    // `cn("tag-" + tone)` never spells the full class out.
    if (
      literals.some(
        (literal) => literal.length >= 3 && name.startsWith(literal)
      )
    ) {
      continue;
    }
    findings.push({ kind: "class", ...definition });
  }

  for (const [name, definition] of propertyDefinitions) {
    if (ignored.has(name)) continue;
    if (referencesProperty(cssReferenceBlob, name)) continue;
    if (referencesProperty(sourceBlob, name)) continue;
    findings.push({ kind: "property", ...definition });
  }

  const tokens = collectTokens(tokenFiles, webRoot);
  for (const [name, definition] of tokens.definitions) {
    if (ignored.has(name)) continue;
    // Another token points at this one, so it survives into the compiled CSS.
    if (tokens.aliased.has(name)) continue;
    if (referencesProperty(cssReferenceBlob, `--${name}`)) continue;
    if (referencesProperty(sourceBlob, `--${name}`)) continue;
    // `\b` treats `-` as a boundary, so this also matches the Tailwind
    // utilities the preset derives from the token, e.g. `bg-text-05`.
    if (wordBoundaryCount(sourceBlob, name) > 0) continue;
    if (wordBoundaryCount(cssReferenceBlob, name) > 0) continue;
    findings.push({ kind: "token", ...definition });
  }

  return findings.sort(
    (a, b) => a.file.localeCompare(b.file) || a.line - b.line
  );
}
