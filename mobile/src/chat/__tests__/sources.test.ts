import { describe, expect, it } from "@jest/globals";

import {
  applySourcePreferences,
  configuredSources,
  getSourceMeta,
  mergeSourcePreferences,
  parseSourcePreferences,
} from "@/chat/sources";

describe("getSourceMeta", () => {
  it("names a known connector the way web does", () => {
    expect(getSourceMeta("google_drive")?.displayName).toBe("Google Drive");
    expect(getSourceMeta("bookstack")?.displayName).toBe("BookStack");
  });

  it("resolves a federated source to its indexed twin", () => {
    expect(getSourceMeta("federated_slack")?.displayName).toBe("Slack");
  });

  it("has nothing to say about a source it doesn't know", () => {
    expect(getSourceMeta("brand_new_connector")).toBeNull();
  });
});

describe("configuredSources", () => {
  it("keeps the order the connectors arrived in", () => {
    expect(configuredSources(["notion", "web", "slack"])).toEqual([
      "notion",
      "web",
      "slack",
    ]);
  });

  it("collapses a source and its federated twin into one row", () => {
    expect(configuredSources(["slack", "federated_slack"])).toEqual(["slack"]);
  });

  it("dedupes repeated connectors of the same type", () => {
    expect(configuredSources(["jira", "jira", "jira"])).toEqual(["jira"]);
  });

  it("drops sources this client can't name, as web does", () => {
    // `not_applicable` is web's fall-through value; it must not survive here either.
    expect(configuredSources(["notion", "some_future_connector"])).toEqual([
      "notion",
    ]);
    expect(configuredSources(["not_applicable"])).toEqual([]);
  });
});

describe("parseSourcePreferences", () => {
  it("reads back a snapshot it wrote", () => {
    const raw = JSON.stringify({ sourcePreferences: { notion: false } });
    expect(parseSourcePreferences(raw)).toEqual({
      sourcePreferences: { notion: false },
    });
  });

  it("treats missing, malformed and wrongly-shaped storage as no preferences", () => {
    expect(parseSourcePreferences(null)).toBeNull();
    expect(parseSourcePreferences("")).toBeNull();
    expect(parseSourcePreferences("{oops")).toBeNull();
    expect(parseSourcePreferences(JSON.stringify({ other: 1 }))).toBeNull();
    expect(
      parseSourcePreferences(JSON.stringify({ sourcePreferences: ["notion"] })),
    ).toBeNull();
    // A non-boolean flag means someone else's schema — the whole snapshot is suspect.
    expect(
      parseSourcePreferences(
        JSON.stringify({ sourcePreferences: { notion: "yes" } }),
      ),
    ).toBeNull();
  });
});

describe("mergeSourcePreferences", () => {
  it("enables everything when nothing was ever saved", () => {
    expect(mergeSourcePreferences(["notion", "web"], null)).toEqual([
      "notion",
      "web",
    ]);
  });

  it("honours saved flags", () => {
    const snapshot = { sourcePreferences: { notion: false, web: true } };
    expect(mergeSourcePreferences(["notion", "web"], snapshot)).toEqual([
      "web",
    ]);
  });

  it("enables a source the snapshot has never seen", () => {
    const snapshot = { sourcePreferences: { notion: false } };
    expect(mergeSourcePreferences(["notion", "jira"], snapshot)).toEqual([
      "jira",
    ]);
  });

  it("ignores saved sources that are no longer available", () => {
    const snapshot = { sourcePreferences: { notion: true, gone: true } };
    expect(mergeSourcePreferences(["notion"], snapshot)).toEqual(["notion"]);
  });
});

describe("applySourcePreferences", () => {
  it("records a flag for every configured source", () => {
    expect(applySourcePreferences(["web"], ["web", "notion"], null)).toEqual({
      sourcePreferences: { web: true, notion: false },
    });
  });

  it("leaves choices made under a differently-scoped agent alone", () => {
    const previous = { sourcePreferences: { jira: false } };
    expect(applySourcePreferences(["web"], ["web"], previous)).toEqual({
      sourcePreferences: { jira: false, web: true },
    });
  });
});
