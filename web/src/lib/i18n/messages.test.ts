import { readFileSync } from "node:fs";
import { join } from "node:path";

function loadKeys(locale: string): string[] {
  const raw = readFileSync(
    join(__dirname, "..", "..", "..", "messages", `${locale}.json`),
    "utf8"
  );
  const data = JSON.parse(raw) as Record<string, unknown>;
  const keys: string[] = [];
  const walk = (obj: Record<string, unknown>, prefix: string) => {
    for (const [k, v] of Object.entries(obj)) {
      const path = prefix ? `${prefix}.${k}` : k;
      if (v && typeof v === "object" && !Array.isArray(v)) {
        walk(v as Record<string, unknown>, path);
      } else {
        keys.push(path);
      }
    }
  };
  walk(data, "");
  return keys.sort();
}

describe("message catalogs", () => {
  it("zh and en have identical key sets", () => {
    expect(loadKeys("zh")).toEqual(loadKeys("en"));
  });

  it("are non-empty", () => {
    expect(loadKeys("zh").length).toBeGreaterThan(0);
  });
});
