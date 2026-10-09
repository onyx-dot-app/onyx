import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import { useProjects, useProjectDetails } from "@/api/chat/projects";

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

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("useProjects", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("fetches the (unpaginated) projects list", async () => {
    apiFetchMock.mockResolvedValueOnce([
      { id: 1, name: "A", chat_sessions: [] },
    ]);

    const { result } = renderHook(() => useProjects(), { wrapper });

    await waitFor(() => expect(result.current.projects).toHaveLength(1));
    expect(apiFetchMock.mock.calls[0]![0]).toBe("/user/projects");
  });
});

describe("useProjectDetails", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("fetches the /details endpoint for a project id", async () => {
    apiFetchMock.mockResolvedValueOnce({
      project: { id: 5, name: "Deep dive", chat_sessions: [] },
      files: [],
    });

    const { result } = renderHook(() => useProjectDetails(5), { wrapper });

    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(apiFetchMock.mock.calls[0]![0]).toBe("/user/projects/5/details");
  });

  it("stays idle when there is no project id", async () => {
    const { result } = renderHook(() => useProjectDetails(null), { wrapper });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(apiFetchMock).not.toHaveBeenCalled();
  });
});
