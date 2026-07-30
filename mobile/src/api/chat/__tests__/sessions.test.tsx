import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import { useChatSessions, type ChatSessionSummary } from "@/api/chat/sessions";

// `jest.mock` is hoisted above the imports by babel-jest.
jest.mock("@/api/client");
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));

// generic `apiFetch<T>` makes jest.mocked() infer `never`; cast to a concrete Mock.
const apiFetchMock = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;

function makeSession(id: string, timeUpdated: string): ChatSessionSummary {
  return {
    id,
    name: id.toUpperCase(),
    persona_id: 0,
    time_created: "2026-01-01T00:00:00Z",
    time_updated: timeUpdated,
    shared_status: "private",
    current_alternate_model: null,
    current_temperature_override: null,
  };
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useChatSessions", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("requests the first page (no cursor) and flattens sessions", async () => {
    apiFetchMock.mockResolvedValueOnce({
      sessions: [makeSession("a", "2026-06-01T00:00:00Z")],
      has_more: false,
    });

    const { result } = renderHook(() => useChatSessions(), { wrapper });

    await waitFor(() => expect(result.current.sessions).toHaveLength(1));

    const firstUrl = apiFetchMock.mock.calls[0]![0];
    expect(firstUrl).toContain("/chat/get-user-chat-sessions?");
    expect(firstUrl).toContain("page_size=50");
    expect(firstUrl).toContain("only_non_project_chats=true");
    expect(firstUrl).not.toContain("before=");
    expect(result.current.hasNextPage).toBe(false);
  });

  it("paginates using the OLDEST loaded session's time_updated as the cursor", async () => {
    // Page is newest-first, so the cursor must be the LAST (oldest) row, not the first.
    apiFetchMock
      .mockResolvedValueOnce({
        sessions: [
          makeSession("a", "2026-06-10T00:00:00Z"),
          makeSession("b", "2026-06-05T00:00:00Z"),
        ],
        has_more: true,
      })
      .mockResolvedValueOnce({
        sessions: [makeSession("c", "2026-05-01T00:00:00Z")],
        has_more: false,
      });

    const { result } = renderHook(() => useChatSessions(), { wrapper });

    await waitFor(() => expect(result.current.hasNextPage).toBe(true));

    await act(async () => {
      await result.current.fetchNextPage();
    });

    await waitFor(() => expect(result.current.sessions).toHaveLength(3));

    const secondUrl = apiFetchMock.mock.calls[1]![0];
    expect(secondUrl).toContain("before=2026-06-05T00%3A00%3A00Z");
    expect(secondUrl).not.toContain("before=2026-06-10T00%3A00%3A00Z");
  });
});
