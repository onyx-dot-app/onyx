import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  jest,
} from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { QUERY_KEYS } from "@/api/query-keys";
import {
  getUserFileStatuses,
  linkFileToProject,
  unlinkFileFromProject,
} from "@/api/files/files";
import { uploadProjectFile } from "@/api/files/upload";
import { pickDocuments, pickImages } from "@/api/files/pickers";
import {
  UserFileStatus,
  type CategorizedFiles,
  type ProjectDetails,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { useProjectFiles } from "@/hooks/useProjectFiles";
import { useUploadStore } from "@/state/uploadStore";

// `jest.mock` is hoisted above the imports by babel-jest.
const mockSettingsRef = { maxMb: null as number | null };

jest.mock("@/api/files/pickers", () => ({
  pickDocuments: jest.fn(),
  pickImages: jest.fn(),
}));
jest.mock("@/api/files/upload", () => {
  let counter = 0;
  return {
    uploadProjectFile: jest.fn(),
    generateTempId: () => `tmp-${++counter}`,
  };
});
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
const uploadMock = uploadProjectFile as unknown as Mock<
  (...args: unknown[]) => Promise<CategorizedFiles>
>;
const statusesMock = getUserFileStatuses as unknown as Mock<
  (ids: string[]) => Promise<ProjectFile[]>
>;
const linkMock = linkFileToProject as unknown as Mock<
  (projectId: number, fileId: string) => Promise<unknown>
>;
const unlinkMock = unlinkFileFromProject as unknown as Mock<
  (projectId: number, fileId: string) => Promise<void>
>;

const PROJECT_ID = 5;
const projectKey = QUERY_KEYS.userProject("https://example.test", PROJECT_ID);

function committedFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return makeProjectFile({ name: "server.pdf", token_count: 9, ...overrides });
}

function setup(committed: ProjectFile[] | null) {
  const client = new QueryClient({
    // gcTime > 0 so manually-seeded (observer-less) query data survives for the
    // polling assertions.
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

describe("useProjectFiles", () => {
  beforeEach(() => {
    useUploadStore.setState({ byProject: new Map() });
    mockSettingsRef.maxMb = null;
    jest.clearAllMocks();
  });

  it("uploads picked documents, invalidates the project, and clears optimistic entries", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1000 },
    ]);
    uploadMock.mockResolvedValue({
      // temp_id echoed back, as the real endpoint does.
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

    expect(uploadMock).toHaveBeenCalledWith(
      { uri: "file:///a.pdf", name: "a.pdf", size: 1000 },
      PROJECT_ID,
      expect.any(String),
      expect.any(Function),
    );
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: projectKey });
    // optimistic entry removed after reconcile
    expect(
      useUploadStore.getState().byProject.get(PROJECT_ID)?.uploads.size ?? 0,
    ).toBe(0);
    expect(result.current.errors).toEqual([]);
  });

  it("blocks oversized files with the size pre-check and never uploads them", async () => {
    mockSettingsRef.maxMb = 1; // 1 MB cap
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///big.pdf", name: "big.pdf", size: 5 * 1024 * 1024 },
    ]);

    const { result } = setup([]);

    await act(async () => {
      await result.current.addDocuments();
    });

    expect(uploadMock).not.toHaveBeenCalled();
    expect(result.current.errors[0]).toContain("big.pdf");
    expect(result.current.errors[0]).toContain("1 MB");
  });

  it("surfaces backend rejected_files reasons", async () => {
    pickImagesMock.mockResolvedValue([
      { uri: "file:///x.heic", name: "x.heic", size: 10 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [],
      rejected_files: [
        { file_name: "x.heic", reason: "Unsupported file type" },
      ],
    });

    const { result } = setup([]);

    await act(async () => {
      await result.current.addImages();
    });

    expect(result.current.errors[0]).toContain("x.heic");
    expect(result.current.errors[0]).toContain("Unsupported file type");
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
    const { result, invalidateSpy } = setup([committedFile({})]);

    await act(async () => {
      await result.current.removeFile("f1");
    });

    expect(unlinkMock).toHaveBeenCalledWith(PROJECT_ID, "f1");
    expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: projectKey });
  });

  it("renders optimistic uploads ahead of committed files", () => {
    useUploadStore
      .getState()
      .begin(PROJECT_ID, [
        committedFile({ id: "tmp-1", status: UserFileStatus.UPLOADING }),
      ]);
    const { result } = setup([committedFile({ id: "f1" })]);

    expect(result.current.files.map((f) => f.id)).toEqual(["tmp-1", "f1"]);
  });

  it("keeps size-rejection messages when a partial batch still has valid files", async () => {
    mockSettingsRef.maxMb = 1;
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///big.pdf", name: "big.pdf", size: 5 * 1024 * 1024 },
      { uri: "file:///ok.pdf", name: "ok.pdf", size: 1000 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [committedFile({ id: "new" })],
      rejected_files: [],
    });

    const { result } = setup([]);
    await act(async () => {
      await result.current.addDocuments();
    });

    expect(uploadMock).toHaveBeenCalledTimes(1); // only the valid file
    expect(result.current.errors.some((e) => e.includes("big.pdf"))).toBe(true);
  });

  it("clears optimistic entries and reports an error when the refetch fails", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 10 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [committedFile({ id: "new" })],
      rejected_files: [],
    });

    const { result, invalidateSpy } = setup([]);
    invalidateSpy.mockRejectedValueOnce(new Error("network"));

    await act(async () => {
      await result.current.addDocuments();
    });

    expect(
      result.current.errors.some((e) => e.includes("didn't refresh")),
    ).toBe(true);
    expect(
      useUploadStore.getState().byProject.get(PROJECT_ID)?.uploads.size ?? 0,
    ).toBe(0);
  });

  it("surfaces an error and skips the refetch when linking fails", async () => {
    linkMock.mockRejectedValueOnce(new Error("boom"));
    const { result, invalidateSpy } = setup([]);

    await act(async () => {
      await result.current.linkRecent("r1");
    });

    expect(result.current.errors.length).toBeGreaterThan(0);
    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("surfaces an error when the photo permission is denied", async () => {
    pickImagesMock.mockRejectedValue(
      new Error("Photo library access was denied."),
    );
    const { result } = setup([]);

    await act(async () => {
      await result.current.addImages();
    });

    expect(uploadMock).not.toHaveBeenCalled();
    expect(result.current.errors.some((e) => e.includes("denied"))).toBe(true);
  });

  describe("status polling", () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });
    afterEach(() => {
      jest.useRealTimers();
    });

    it("polls indexing files every 3s and patches the cached status", async () => {
      statusesMock.mockResolvedValue([
        committedFile({
          id: "f1",
          status: UserFileStatus.COMPLETED,
          token_count: 42,
        }),
      ]);

      const { client } = setup([
        committedFile({ id: "f1", status: UserFileStatus.INDEXING }),
      ]);
      client.setQueryData<ProjectDetails>(projectKey, {
        project: {
          id: PROJECT_ID,
          name: "P",
          description: null,
          created_at: "2026-01-01T00:00:00Z",
          instructions: null,
          chat_sessions: [],
        },
        files: [committedFile({ id: "f1", status: UserFileStatus.INDEXING })],
        persona_id_to_is_featured: null,
      });

      await act(async () => {
        await jest.advanceTimersByTimeAsync(3000);
      });

      expect(statusesMock).toHaveBeenCalledWith(["f1"]);
      const patched = client.getQueryData<ProjectDetails>(projectKey);
      expect(patched?.files?.[0].status).toBe(UserFileStatus.COMPLETED);
      expect(patched?.files?.[0].token_count).toBe(42);
    });

    it("does not poll when every file is already terminal", async () => {
      setup([committedFile({ id: "f1", status: UserFileStatus.COMPLETED })]);

      await act(async () => {
        await jest.advanceTimersByTimeAsync(3000);
      });

      expect(statusesMock).not.toHaveBeenCalled();
    });
  });
});
