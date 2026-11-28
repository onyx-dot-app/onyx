import {
  stripSessionPrefix,
  sanitizePathsInText,
  parseOutputLink,
} from "@/app/craft/utils/pathSanitizer";

describe("parseOutputLink", () => {
  it.each([
    ["outputs/slides/deck.pptx", "outputs/slides/deck.pptx"],
    ["./outputs/Scenic%20Route.pptx", "outputs/Scenic Route.pptx"],
    ["outputs/%E6%97%85%E8%A1%8C.pdf", "outputs/旅行.pdf"],
  ])("accepts a session-relative output: %s", (href, expected) => {
    expect(parseOutputLink(href)).toBe(expected);
  });

  it.each([
    "outputs",
    "outputs/",
    "outputs//deck.pptx",
    "outputs/../secret",
    "outputs/./deck.pptx",
    "outputs/%2e%2e/secret",
    "outputs/%252e%252e/secret",
    "outputs/nested%2f..%2fsecret",
    "outputs/nested%5c..%5csecret",
    "outputs/..\\secret",
    "outputs/\\evil.example/x",
    "outputs/.env",
    "outputs/deck.pptx?session_id=another",
    "outputs/deck.pptx#fragment",
    "outputs/deck.pptx%3Fsession_id=another",
    "outputs/deck.pptx%23fragment",
    "outputs/%00deck.pptx",
    "outputs/%0adeck.pptx",
    "outputs/\u0000deck.pptx",
    "outputs/%zz.pptx",
    "outputs/%E0%A4.pptx",
    "outputs/https:evil",
    "outputs/%252fetc/passwd",
    "/outputs/deck.pptx",
    "../outputs/deck.pptx",
    "attachments/deck.pptx",
    "https://evil.example/outputs/deck.pptx",
    "//evil.example/outputs/deck.pptx",
    "file:///outputs/deck.pptx",
    "javascript:alert(1)",
    "/api/build/sessions/another/artifacts/outputs/deck.pptx",
  ])("rejects an unsafe or unsupported path: %s", (href) => {
    expect(parseOutputLink(href)).toBeNull();
  });
});

// =============================================================================
// stripSessionPrefix
// =============================================================================

describe("stripSessionPrefix", () => {
  it("returns empty string for empty input", () => {
    expect(stripSessionPrefix("")).toBe("");
  });

  // ── Local dev (sandboxes + sessions) ────────────────────────────────

  it("strips local sandboxes/sessions prefix", () => {
    expect(
      stripSessionPrefix(
        "/Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/outputs/web/AGENTS.md"
      )
    ).toBe("outputs/web/AGENTS.md");
  });

  it("strips local sandboxes/sessions prefix for user_library/ directory", () => {
    expect(
      stripSessionPrefix(
        "/Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/user_library/docs/report.pdf"
      )
    ).toBe("user_library/docs/report.pdf");
  });

  it("strips sandboxes/sessions even with non-standard prefix", () => {
    expect(
      stripSessionPrefix(
        "/data/sandboxes/abcdef1234567890abcdef1234567890ab/sessions/abcdef1234567890abcdef1234567890ab/file.txt"
      )
    ).toBe("file.txt");
  });

  // ── Kubernetes (sessions only) ──────────────────────────────────────

  it("strips kubernetes sessions prefix", () => {
    expect(
      stripSessionPrefix(
        "/workspace/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/outputs/web/page.tsx"
      )
    ).toBe("outputs/web/page.tsx");
  });

  it("strips kubernetes sessions with short prefix", () => {
    expect(
      stripSessionPrefix("/some/path/sessions/def-456/user_library/data.json")
    ).toBe("user_library/data.json");
  });

  // ── Already relative ────────────────────────────────────────────────

  it("returns already-relative paths unchanged", () => {
    expect(stripSessionPrefix("outputs/web/page.tsx")).toBe(
      "outputs/web/page.tsx"
    );
  });

  it("strips leading slash from short paths", () => {
    expect(stripSessionPrefix("/file.txt")).toBe("file.txt");
  });

  // ── Title field (no leading /) ──────────────────────────────────────

  it("handles title field without leading slash (sandboxes path)", () => {
    expect(
      stripSessionPrefix(
        "Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/outputs/web/page.tsx"
      )
    ).toBe("outputs/web/page.tsx");
  });

  // ── Fallback (unknown format, >3 segments) ──────────────────────────

  it("falls back to last 3 segments for unknown deep paths", () => {
    expect(stripSessionPrefix("/some/unknown/deep/path/to/file.tsx")).toBe(
      "path/to/file.tsx"
    );
  });

  // ── Short paths ─────────────────────────────────────────────────────

  it("returns short relative path as-is", () => {
    expect(stripSessionPrefix("file.txt")).toBe("file.txt");
  });

  it("returns 3-segment path as-is", () => {
    expect(stripSessionPrefix("a/b/c")).toBe("a/b/c");
  });
});

// =============================================================================
// sanitizePathsInText
// =============================================================================

describe("sanitizePathsInText", () => {
  it("returns empty string for empty input", () => {
    expect(sanitizePathsInText("")).toBe("");
  });

  // ── Bash commands ───────────────────────────────────────────────────

  it("strips local sandboxes path from cd command", () => {
    expect(
      sanitizePathsInText(
        "cd /Users/wenxi-onyx/data/sandboxes/abc-123/sessions/def-456/outputs/web && python3 prepare.py"
      )
    ).toBe("cd outputs/web && python3 prepare.py");
  });

  it("strips multiple paths in a single command", () => {
    expect(
      sanitizePathsInText(
        "chmod +x /Users/wenxi/data/sandboxes/abc/sessions/def/outputs/web/prepare.sh && /Users/wenxi/data/sandboxes/abc/sessions/def/outputs/web/prepare.sh"
      )
    ).toBe("chmod +x outputs/web/prepare.sh && outputs/web/prepare.sh");
  });

  // ── Output listings ─────────────────────────────────────────────────

  it("strips kubernetes paths from ls output", () => {
    expect(
      sanitizePathsInText(
        "/workspace/sessions/def-456/outputs/web/page.tsx\n/workspace/sessions/def-456/outputs/web/globals.css"
      )
    ).toBe("outputs/web/page.tsx\noutputs/web/globals.css");
  });

  it("strips local paths from find output", () => {
    expect(
      sanitizePathsInText(
        "find /Users/wenxi/data/sandboxes/abc/sessions/def/user_library/docs -type d"
      )
    ).toBe("find user_library/docs -type d");
  });

  // ── No paths — passthrough ──────────────────────────────────────────

  it("returns text without sandbox/session paths unchanged", () => {
    const text =
      "total 0\ndrwxr-xr-x@ 3 wenxi-onyx  staff  96 Jan 21 15:18 .\n";
    expect(sanitizePathsInText(text)).toBe(text);
  });

  // ── Error messages ──────────────────────────────────────────────────

  it("strips paths from error messages", () => {
    expect(
      sanitizePathsInText(
        "Error: ENOENT: no such file or directory, open '/workspace/sessions/abc-123/outputs/web/missing.tsx'"
      )
    ).toBe(
      "Error: ENOENT: no such file or directory, open 'outputs/web/missing.tsx'"
    );
  });
});
