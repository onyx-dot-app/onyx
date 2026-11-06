import { externalAppDisplayUrl } from "@/lib/plugins/externalAppDisplayUrl";

describe("externalAppDisplayUrl", () => {
  it.each([
    ["https://api\\.linear\\.app/.*", "https://api.linear.app"],
    ["^https://api\\.linear\\.app/.*$", "https://api.linear.app"],
    ["https://api.acme.test/*", "https://api.acme.test"],
    ["http://localhost:8080/api/*", "http://localhost:8080"],
    ["https://api.acme.test", "https://api.acme.test"],
    ["https://(api|www)\\.acme\\.test/.*", ""],
    ["https://.*\\.acme\\.test/.*", ""],
    ["https://[a-z]+\\.acme\\.test/.*", ""],
    ["https://user:password@acme.test/*", ""],
    ["not a URL", ""],
    ["https://api.acme.test:99999/*", ""],
  ])("formats %s without exposing matching syntax", (pattern, expected) => {
    expect(externalAppDisplayUrl([pattern])).toBe(expected);
  });

  it("deduplicates origins and leaves source patterns unchanged", () => {
    const patterns = Object.freeze([
      "https://api\\.linear\\.app/.*",
      "https://api\\.linear\\.app/graphql",
      "https://uploads\\.linear\\.app/.*",
    ]);
    expect(externalAppDisplayUrl(patterns)).toBe(
      "https://api.linear.app, https://uploads.linear.app"
    );
    expect(patterns[0]).toBe("https://api\\.linear\\.app/.*");
    expect(externalAppDisplayUrl([])).toBe("");
  });
});
