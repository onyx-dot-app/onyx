import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch, type ApiFetchInit } from "@/api/client";
import { ApiError } from "@/api/errors";
import { useConnectorSources } from "@/hooks/useConnectorSources";

jest.mock("@/api/client");
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));

const apiFetchMock = apiFetch as unknown as Mock<
  (path: string, init?: ApiFetchInit) => Promise<unknown>
>;

const CONNECTOR_ROWS = [
  { has_successful_run: true, source: "notion", status: "ACTIVE" },
];

/*
 * `/settings` is stubbed rather than `useWorkspaceSettings`, because what the hook keys off is that
 * hook's own defaulting: an outage leaves `vector_db_enabled` at its optimistic `true` while
 * `isPending` goes false, and stubbing above that layer can't tell an outage from a `true` answer.
 */
type SettingsOutcome =
  | { kind: "ok"; vectorDb: boolean }
  | { kind: "pending" }
  | { kind: "error" };

function mockApi(settings: SettingsOutcome, federated: unknown[] = []): void {
  apiFetchMock.mockImplementation((path: string) => {
    switch (path) {
      case "/settings":
        if (settings.kind === "pending") return new Promise<never>(() => {});
        if (settings.kind === "error") {
          return Promise.reject(new ApiError({ status: 500 }));
        }
        return Promise.resolve({ vector_db_enabled: settings.vectorDb });
      case "/manage/connector-status":
        return Promise.resolve(CONNECTOR_ROWS);
      case "/federated":
        return Promise.resolve(federated);
      default:
        return Promise.resolve([]);
    }
  });
}

function connectorCalls(): number {
  return apiFetchMock.mock.calls.filter(
    ([path]) => path === "/manage/connector-status",
  ).length;
}

function renderSources() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(() => useConnectorSources(), { wrapper });
}

describe("useConnectorSources", () => {
  beforeEach(() => {
    apiFetchMock.mockReset();
  });

  it("asks for the connector list once the vector DB is confirmed", async () => {
    mockApi({ kind: "ok", vectorDb: true });

    const { result } = renderSources();

    await waitFor(() => expect(result.current.sources).toEqual(["notion"]));
    expect(connectorCalls()).toBe(1);
  });

  it("never asks for it when the deployment runs without a vector DB", async () => {
    mockApi({ kind: "ok", vectorDb: false });

    const { result } = renderSources();

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(connectorCalls()).toBe(0);
  });

  it("waits for the setting rather than guessing at it", async () => {
    /*
     * The whole `/manage` router answers 501 without a vector DB, and the retry doubles it — so a
     * guess here costs those deployments two failed requests on every launch.
     */
    mockApi({ kind: "pending" });

    renderSources();

    await waitFor(() => expect(apiFetchMock).toHaveBeenCalled());
    expect(connectorCalls()).toBe(0);
  });

  it("falls back to asking when the settings call itself failed", async () => {
    // A settings outage must not empty the picker for everyone, so the optimistic default stands.
    mockApi({ kind: "error" });

    const { result } = renderSources();

    await waitFor(() => expect(result.current.sources).toEqual(["notion"]));
    expect(connectorCalls()).toBe(1);
  });

  it("still offers federated connectors without a vector DB", async () => {
    // Queried live rather than indexed, so they don't depend on the vector DB at all.
    mockApi({ kind: "ok", vectorDb: false }, [
      { id: 1, source: "federated_slack", name: "" },
    ]);

    const { result } = renderSources();

    await waitFor(() =>
      expect(result.current.sources).toEqual(["federated_slack"]),
    );
    expect(connectorCalls()).toBe(0);
  });
});
