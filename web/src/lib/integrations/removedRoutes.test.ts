/**
 * The integrations API replaced these routes. No web code may call them.
 */
import fs from "fs";
import path from "path";

const SRC = path.resolve(__dirname, "../..");
const SELF = path.resolve(__filename);

const REMOVED_ROUTES: readonly RegExp[] = [
  /\/api\/mcp\/servers(?!\/craft\b)/,
  /\/api\/mcp\/user-credentials/,
  /\/api\/mcp\/oauth\/connect/,
  /\/api\/oauth-config/,
  /\/api\/admin\/oauth-config/,
  /\/api\/build\/admin\/apps/,
  // GET /build/apps and the connect decision route stay.
  /\/api\/build\/apps\/(?!connect\/)/,
  /BUILD_API_BASE\}\/(?:admin\/)?apps\/(?!connect\/)/,
  /\/api\/user-oauth-token/,
  /\/api\/action-policies\/(?!integration\/)/,
  /\/api\/admin\/tool\/status/,
  /\/api\/admin\/mcp\/servers?\//,
  /\/api\/admin\/mcp\/servers\b/,
];

function sourceFiles(dir: string): string[] {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return /\.(?:ts|tsx|js|jsx)$/.test(entry.name) && full !== SELF
      ? [full]
      : [];
  });
}

test("web code calls no route that the integrations API removed", () => {
  const hits = sourceFiles(SRC).flatMap((file) =>
    fs
      .readFileSync(file, "utf8")
      .split("\n")
      .flatMap((line, index) =>
        REMOVED_ROUTES.some((route) => route.test(line))
          ? [`${path.relative(SRC, file)}:${index + 1}: ${line.trim()}`]
          : []
      )
  );
  expect(hits).toEqual([]);
});
