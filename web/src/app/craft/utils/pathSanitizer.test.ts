import { stripSessionPrefix, sanitizePathsInText } from "./pathSanitizer";

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

  it("strips local sandboxes/sessions prefix for files/ directory", () => {
    expect(
      stripSessionPrefix(
        "/Users/wenxi-onyx/data/sandboxes/b29c196e-fa14-46b8-8182-ff4a7f67b47b/sessions/9c7662c1-785f-4f1c-b9e0-9021ddbf2893/files/linear/Engineering/ticket.json"
      )
    ).toBe("files/linear/Engineering/ticket.json");
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
      stripSessionPrefix("/some/path/sessions/def-456/files/data.json")
    ).toBe("files/data.json");
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
        "find /Users/wenxi/data/sandboxes/abc/sessions/def/files/linear -type d"
      )
    ).toBe("find files/linear -type d");
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
