import { resolve } from "node:path";

import { findDeadCss, type CssFinding } from "../css.ts";

/**
 * These cover the four rules in the CSS checker that carry real logic, and so
 * carry real risk of deleting live code: prefix matching for dynamically built
 * class names, style-dictionary alias resolution, and the mobile corpus.
 */

const FIXTURES = resolve(import.meta.dirname, "fixtures");

async function run(): Promise<CssFinding[]> {
  return findDeadCss({
    webRoot: resolve(FIXTURES, "web"),
    extraCorpusRoots: [resolve(FIXTURES, "mobile")],
    ignore: [],
  });
}

function names(findings: readonly CssFinding[], kind: CssFinding["kind"]) {
  return findings
    .filter((finding) => finding.kind === kind)
    .map((finding) => finding.name);
}

describe("findDeadCss", () => {
  it("reports a class that nothing references", async () => {
    expect(names(await run(), "class")).toContain("tag-orphan");
  });

  it("keeps a class that a component applies directly", async () => {
    expect(names(await run(), "class")).not.toContain("tag-root");
  });

  it("keeps a class built by string concatenation", async () => {
    // The source spells only `"tag-tone-"`, never the full class name.
    expect(names(await run(), "class")).not.toContain("tag-tone-warning");
  });

  it("reports a custom property that nothing references", async () => {
    expect(names(await run(), "property")).toContain("--tag-unused");
  });

  it("keeps a custom property referenced through var()", async () => {
    expect(names(await run(), "property")).not.toContain("--tag-text");
  });

  it("reports a token that nothing references", async () => {
    expect(names(await run(), "token")).toContain("orphan-primitive");
  });

  it("keeps a token reached only through a style-dictionary alias", async () => {
    // `grey-90` is referenced solely as `{grey-90}` by the `text-05` token.
    expect(names(await run(), "token")).not.toContain("grey-90");
  });

  it("keeps a token referenced only from the mobile app", async () => {
    expect(names(await run(), "token")).not.toContain("mobile-only-size");
  });
});
