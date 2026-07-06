import { describe, expect, it, jest } from "@jest/globals";
import type { Query } from "@tanstack/react-query";

import { dehydrateOptions } from "@/query/client";
import { QUERY_KEYS } from "@/api/query-keys";

// Avoid the real MMKV-backed storage at module load; the persister isn't exercised here.
jest.mock("@/state/storage", () => ({
  makeMmkvStorage: () => ({
    getItem: () => null,
    setItem: () => {},
    removeItem: () => {},
  }),
  queryStorage: {},
}));

function wouldPersist(queryKey: readonly unknown[]): boolean {
  return (
    dehydrateOptions.shouldDehydrateQuery?.({
      queryKey,
      state: { status: "success" },
    } as unknown as Query) ?? false
  );
}

describe("dehydrateOptions PII exclusion", () => {
  const url = "https://example.test";

  it("never persists chat session/message queries to the unencrypted disk cache", () => {
    expect(wouldPersist(QUERY_KEYS.chatSessions(url))).toBe(false);
    expect(wouldPersist(QUERY_KEYS.chatSession(url, "abc"))).toBe(false);
  });

  it("never persists the current-user query", () => {
    expect(wouldPersist(QUERY_KEYS.me(url))).toBe(false);
  });

  it("never persists project queries (their chats' titles are PII)", () => {
    expect(wouldPersist(QUERY_KEYS.userProjects(url))).toBe(false);
    expect(wouldPersist(QUERY_KEYS.userProject(url, 5))).toBe(false);
  });

  it("excludes future chat-* keys by default (default-deny)", () => {
    expect(wouldPersist(["chat-messages", url])).toBe(false);
    expect(wouldPersist(["chat-history", url, "abc"])).toBe(false);
  });

  it("never persists workspace-scoped config (agents, settings)", () => {
    expect(wouldPersist(QUERY_KEYS.agents(url))).toBe(false);
    expect(wouldPersist(QUERY_KEYS.workspaceSettings(url))).toBe(false);
  });

  it("persists non-PII success queries", () => {
    expect(wouldPersist(QUERY_KEYS.authType(url))).toBe(true);
  });
});
