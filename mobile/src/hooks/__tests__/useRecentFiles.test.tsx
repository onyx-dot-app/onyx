import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { apiFetch } from "@/api/client";
import { UserFileStatus } from "@/chat/contracts/projects";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { useRecentFiles } from "@/hooks/useRecentFiles";
import { useUserFileStore } from "@/state/userFileStore";

jest.mock("@/api/client", () => ({ apiFetch: jest.fn() }));
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));

const apiFetchMock = apiFetch as unknown as Mock<
  (p: string) => Promise<unknown>
>;

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const DRAFT = { kind: "draft" as const, draftKey: "d:" };

function resetStore() {
  useUserFileStore.setState({
    filesById: {},
    serverIdToClientId: {},
    tasksById: {},
    progressById: {},
    epochCounter: 0,
  });
}

describe("useRecentFiles", () => {
  beforeEach(() => {
    resetStore();
    jest.clearAllMocks();
  });

  it("prepends still-uploading files to the fetched list", async () => {
    useUserFileStore.getState().beginUpload(DRAFT, [
      {
        clientId: "tmp-1",
        file: makeProjectFile({
          id: "tmp-1",
          status: UserFileStatus.UPLOADING,
        }),
      },
    ]);
    apiFetchMock.mockResolvedValue([
      makeProjectFile({ id: "f1", status: UserFileStatus.COMPLETED }),
    ]);

    const { result } = renderHook(() => useRecentFiles(true), { wrapper });

    await waitFor(() =>
      expect(result.current.data?.map((f) => f.id)).toEqual(["tmp-1", "f1"]),
    );
  });

  it("dedupes an upload that has reconciled into the fetched list (shown once)", async () => {
    const epoch = useUserFileStore.getState().beginUpload(DRAFT, [
      {
        clientId: "tmp-1",
        file: makeProjectFile({
          id: "tmp-1",
          status: UserFileStatus.UPLOADING,
        }),
      },
    ]);
    useUserFileStore.getState().reconcile(
      [
        makeProjectFile({
          id: "f1",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ],
      epoch,
    );
    apiFetchMock.mockResolvedValue([
      makeProjectFile({ id: "f1", status: UserFileStatus.INDEXING }),
    ]);

    const { result } = renderHook(() => useRecentFiles(true), { wrapper });

    await waitFor(() =>
      expect(result.current.data?.map((f) => f.id)).toEqual(["f1"]),
    );
  });

  it("logs a fetch failure and still surfaces it as an error (not a silent empty picker)", async () => {
    const warnSpy = jest.spyOn(console, "warn").mockImplementation(() => {});
    apiFetchMock.mockRejectedValue(new Error("boom"));

    const { result } = renderHook(() => useRecentFiles(true), { wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(warnSpy).toHaveBeenCalledWith(
      "recent files fetch failed",
      expect.any(Error),
    );
    warnSpy.mockRestore();
  });
});
