import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { generateTempId } from "@/api/files/upload";
import {
  UserFileStatus,
  type CategorizedFiles,
} from "@/chat/contracts/projects";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { toast } from "@/hooks/useToast";
import { useUpload } from "@/hooks/useUpload";
import { useUserFileStore, type UploadTarget } from "@/state/userFileStore";

const mockSettingsRef = { maxMb: null as number | null };
let mockTransportResult: Promise<CategorizedFiles>;

jest.mock("@/hooks/useToast", () => ({
  toast: {
    warning: jest.fn(),
    error: jest.fn(),
    success: jest.fn(),
    info: jest.fn(),
    dismiss: jest.fn(),
    clearAll: jest.fn(),
  },
}));
jest.mock("@/api/files/upload", () => ({ generateTempId: jest.fn() }));
jest.mock("@/api/files/transport", () => ({
  getUploadTransport: () => ({
    kind: "foreground",
    upload: () => ({ result: mockTransportResult, cancel: jest.fn() }),
  }),
}));
jest.mock("@/api/settings", () => ({
  useWorkspaceSettings: () => ({
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: mockSettingsRef.maxMb,
    },
  }),
}));
jest.mock("@/state/session", () => ({
  useSession: (selector: (s: { serverUrl: string | null }) => unknown) =>
    selector({ serverUrl: "https://example.test" }),
}));

const generateTempIdMock = generateTempId as unknown as Mock<() => string>;
const toastWarn = toast.warning as unknown as Mock<(m: string) => string>;
const toastError = toast.error as unknown as Mock<(m: string) => string>;

const DRAFT: UploadTarget = { kind: "draft", draftKey: "chat-1:" };
const MB = 1024 * 1024;
const asset = (name: string, size?: number) => ({
  uri: `file:///${name}`,
  name,
  size,
});

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function reset() {
  useUserFileStore.setState({
    filesById: {},
    serverIdToClientId: {},
    tasksById: {},
    progressById: {},
    epochCounter: 0,
  });
}

describe("useUpload", () => {
  beforeEach(() => {
    reset();
    mockSettingsRef.maxMb = null;
    jest.clearAllMocks();
    let counter = 0;
    generateTempIdMock.mockImplementation(() => `tmp-${++counter}`);
  });

  it("returns no ids and toasts a size error when every file is oversized (BUG2 fallback)", () => {
    const { result } = renderHook(() => useUpload(), { wrapper });
    let ids: string[] = [];
    act(() => {
      // 150 MB is under no server cap but over the 100 MB finite fallback → rejected client-side.
      ids = result.current.upload([asset("huge.zip", 150 * MB)], DRAFT);
    });
    expect(ids).toEqual([]);
    expect(toastWarn).toHaveBeenCalledWith(expect.stringContaining("huge.zip"));
    expect(useUserFileStore.getState().tasksById).toEqual({});
  });

  it("inserts an optimistic record synchronously, then reconciles the server file", async () => {
    mockTransportResult = Promise.resolve({
      user_files: [
        makeProjectFile({
          id: "u1",
          file_id: "blob-1",
          temp_id: "tmp-1",
          status: UserFileStatus.COMPLETED,
        }),
      ],
      rejected_files: [],
    });

    const { result } = renderHook(() => useUpload(), { wrapper });
    let ids: string[] = [];
    act(() => {
      ids = result.current.upload([asset("a.pdf", 10)], DRAFT);
    });
    // Optimistic record is present immediately (chips render before the transfer finishes).
    expect(ids).toEqual(["tmp-1"]);
    expect(useUserFileStore.getState().filesById["tmp-1"]!.file.status).toBe(
      UserFileStatus.UPLOADING,
    );

    await waitFor(() =>
      expect(useUserFileStore.getState().filesById["tmp-1"]!.file.file_id).toBe(
        "blob-1",
      ),
    );
  });

  it("toasts an error and drops the optimistic record when the transfer fails", async () => {
    mockTransportResult = Promise.reject(new Error("network down"));

    const { result } = renderHook(() => useUpload(), { wrapper });
    act(() => {
      result.current.upload([asset("a.pdf", 10)], DRAFT);
    });

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(expect.stringContaining("a.pdf")),
    );
    expect(useUserFileStore.getState().filesById["tmp-1"]).toBeUndefined();
  });

  it("stays silent when an in-flight attachment is removed before the transfer rejects", async () => {
    // rejecting the transport promise mimics controller.abort()
    mockTransportResult = Promise.reject(new Error("aborted"));

    const { result } = renderHook(() => useUpload(), { wrapper });
    act(() => {
      result.current.upload([asset("a.pdf", 10)], DRAFT);
      // remove before the rejection lands, clearing the task
      result.current.remove("tmp-1", DRAFT);
    });
    expect(useUserFileStore.getState().tasksById["tmp-1"]).toBeUndefined();

    // drain microtasks: catch sees no task → no toast
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(toastError).not.toHaveBeenCalled();
  });
});
