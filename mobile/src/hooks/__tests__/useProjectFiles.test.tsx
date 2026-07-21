import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import { linkFileToProject, unlinkFileFromProject } from "@/api/files/files";
import { generateTempId } from "@/api/files/upload";
import { pickDocuments, pickImages } from "@/api/files/pickers";
import {
  UserFileStatus,
  type CategorizedFiles,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { toast } from "@/hooks/useToast";
import { useProjectFiles } from "@/hooks/useProjectFiles";
import { useUserFileStore } from "@/state/userFileStore";

// `jest.mock` is hoisted above the imports by babel-jest.
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
jest.mock("@/api/files/pickers", () => ({
  pickDocuments: jest.fn(),
  pickImages: jest.fn(),
}));
jest.mock("@/api/files/upload", () => ({ generateTempId: jest.fn() }));
jest.mock("@/api/files/transport", () => ({
  getUploadTransport: () => ({
    kind: "foreground",
    upload: () => ({ result: mockTransportResult, cancel: jest.fn() }),
  }),
}));
jest.mock("@/api/files/files", () => ({
  getUserFileStatuses: jest.fn(),
  linkFileToProject: jest.fn(),
  unlinkFileFromProject: jest.fn(),
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

const pickDocumentsMock = pickDocuments as unknown as Mock<
  () => Promise<{ uri: string; name: string; size?: number }[]>
>;
const pickImagesMock = pickImages as unknown as Mock<
  () => Promise<{ uri: string; name: string; size?: number }[]>
>;
const linkMock = linkFileToProject as unknown as Mock<
  (projectId: number, fileId: string) => Promise<unknown>
>;
const unlinkMock = unlinkFileFromProject as unknown as Mock<
  (projectId: number, fileId: string) => Promise<void>
>;
const generateTempIdMock = generateTempId as unknown as Mock<() => string>;
const toastWarn = toast.warning as unknown as Mock<(m: string) => string>;
const toastError = toast.error as unknown as Mock<(m: string) => string>;

const PROJECT_ID = 5;
const projectKey = QUERY_KEYS.userProject("https://example.test", PROJECT_ID);

function committedFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return makeProjectFile({ name: "server.pdf", token_count: 9, ...overrides });
}

function setup(committed: ProjectFile[] | null) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  const invalidateSpy = jest.spyOn(client, "invalidateQueries");
  function wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
  }
  const view = renderHook(() => useProjectFiles(PROJECT_ID, committed), {
    wrapper,
  });
  return { client, invalidateSpy, ...view };
}

function resetStore() {
  useUserFileStore.setState({
    filesById: {},
    serverIdToClientId: {},
    tasksById: {},
    progressById: {},
    epochCounter: 0,
  });
}

describe("useProjectFiles", () => {
  beforeEach(() => {
    resetStore();
    mockSettingsRef.maxMb = null;
    jest.clearAllMocks();
    let counter = 0;
    generateTempIdMock.mockImplementation(() => `tmp-${++counter}`);
  });

  it("uploads picked docs, reconciles, invalidates Query, and keeps the record (no hand-off)", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1000 },
    ]);
    mockTransportResult = Promise.resolve({
      user_files: [
        committedFile({
          id: "new",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ],
      rejected_files: [],
    });

    const { result, invalidateSpy } = setup([]);
    await act(async () => {
      await result.current.addDocuments();
    });

    await waitFor(() =>
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: projectKey }),
    );
    // C: the record stays in the store (no hand-off removal); the task lingers as succeeded and
    // the file is reconciled to its server id/status. The project-details refetch re-hydrates it.
    const state = useUserFileStore.getState();
    expect(state.tasksById["tmp-1"]?.status).toBe("succeeded");
    expect(state.filesById["tmp-1"]?.file.id).toBe("new");
    expect(state.filesById["tmp-1"]?.file.status).toBe(UserFileStatus.INDEXING);
    expect(toastError).not.toHaveBeenCalled();
  });

  it("blocks oversized files with the size pre-check (BUG2 finite fallback) and toasts", async () => {
    mockSettingsRef.maxMb = 1;
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///big.pdf", name: "big.pdf", size: 5 * 1024 * 1024 },
    ]);

    const { result } = setup([]);
    await act(async () => {
      await result.current.addDocuments();
    });

    expect(toastWarn).toHaveBeenCalledWith(expect.stringContaining("big.pdf"));
    expect(useUserFileStore.getState().tasksById).toEqual({});
  });

  it("surfaces backend rejected_files reasons as an error toast", async () => {
    pickImagesMock.mockResolvedValue([
      { uri: "file:///x.heic", name: "x.heic", size: 10 },
    ]);
    mockTransportResult = Promise.resolve({
      user_files: [],
      rejected_files: [
        { file_name: "x.heic", reason: "Unsupported file type" },
      ],
    });

    const { result } = setup([]);
    await act(async () => {
      await result.current.addImages();
    });

    await waitFor(() =>
      expect(toastError).toHaveBeenCalledWith(
        expect.stringContaining("Unsupported file type"),
      ),
    );
  });

  it("links a recent file and invalidates the project", async () => {
    linkMock.mockResolvedValue({});
    const { result, invalidateSpy } = setup([]);

    await act(async () => {
      await result.current.linkRecent("recent-9");
    });

    expect(linkMock).toHaveBeenCalledWith(PROJECT_ID, "recent-9");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: projectKey });
  });

  it("removes (unlinks) a file and invalidates the project", async () => {
    unlinkMock.mockResolvedValue(undefined);
    const { result, invalidateSpy } = setup([committedFile({ id: "f1" })]);

    await act(async () => {
      await result.current.removeFile("f1");
    });

    expect(unlinkMock).toHaveBeenCalledWith(PROJECT_ID, "f1");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: projectKey });
  });

  it("renders optimistic uploads (from engine tasks) ahead of committed files", () => {
    useUserFileStore
      .getState()
      .beginUpload({ kind: "project", projectId: PROJECT_ID }, [
        {
          clientId: "tmp-1",
          file: committedFile({
            id: "tmp-1",
            status: UserFileStatus.UPLOADING,
          }),
        },
      ]);
    const { result } = setup([committedFile({ id: "f1" })]);

    expect(result.current.files.map((f) => f.id)).toEqual(["tmp-1", "f1"]);
  });

  describe("store as SSOT for file data", () => {
    it("seeds the committed prop into the store and renders from it", async () => {
      const { result } = setup([committedFile({ id: "f1" })]);

      await waitFor(() =>
        expect(useUserFileStore.getState().serverIdToClientId["f1"]).toBe("f1"),
      );
      expect(useUserFileStore.getState().filesById["f1"]?.file.name).toBe(
        "server.pdf",
      );
      expect(result.current.files.map((f) => f.id)).toEqual(["f1"]);
    });

    it("renders a just-committed upload once and clears its optimistic task", async () => {
      // A project upload reconciled to server id "new" (its temp-keyed record + task linger).
      useUserFileStore
        .getState()
        .beginUpload({ kind: "project", projectId: PROJECT_ID }, [
          {
            clientId: "tmp-1",
            file: committedFile({
              id: "tmp-1",
              status: UserFileStatus.UPLOADING,
            }),
          },
        ]);
      useUserFileStore.getState().reconcile([
        committedFile({
          id: "new",
          temp_id: "tmp-1",
          status: UserFileStatus.INDEXING,
        }),
      ]);

      // Project-details refetch brings the same file back keyed by its server id "new".
      const { result } = setup([
        committedFile({ id: "new", status: UserFileStatus.INDEXING }),
      ]);

      // upsert maps "new" back to the temp clientId and clears the succeeded task, so the file
      // renders exactly once (committed) and can't resurrect as a phantom on a later unlink.
      await waitFor(() =>
        expect(useUserFileStore.getState().tasksById["tmp-1"]).toBeUndefined(),
      );
      expect(useUserFileStore.getState().serverIdToClientId["new"]).toBe(
        "tmp-1",
      );
      expect(result.current.files.map((f) => f.id)).toEqual(["new"]);
    });
  });
});
