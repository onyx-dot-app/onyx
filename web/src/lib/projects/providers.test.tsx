import React, { PropsWithChildren } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import englishMessages from "@/i18n/messages/en.json";
import { ProjectsProvider, useProjectsContext } from "@/lib/projects/providers";
import { type ProjectFile, UserFileStatus } from "@/lib/projects/types";
import { ChatFileType } from "@/app/app/types";
import type { UploadFilesOptions } from "@/lib/projects/svc";
import { cancelUpload } from "@/lib/projects/uploadProgress";

const mockUploadFiles = jest.fn();
const mockGetRecentFiles = jest.fn();
const mockToastWarning = jest.fn();
const mockToastError = jest.fn();
const mockGetUserFileStatuses = jest.fn();
const mockDeleteUserFile = jest.fn();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => "/app",
  useSearchParams: () => new URLSearchParams(),
}));

jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({ openNewSession: jest.fn() }),
}));

jest.mock("@/lib/projects/hooks", () => ({
  useProjects: () => ({
    projects: [],
    refreshProjects: jest.fn().mockResolvedValue([]),
  }),
}));

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({
    user_file_max_upload_size_mb: 1,
    enterprise: null,
    appName: "Onyx",
    vectorDbEnabled: true,
    isLoading: false,
    error: undefined,
  }),
}));

jest.mock("@opal/layouts/toast/store", () => ({
  toast: {
    warning: (...args: unknown[]) => mockToastWarning(...args),
    error: (...args: unknown[]) => mockToastError(...args),
    success: jest.fn(),
  },
}));

jest.mock("@/lib/projects/svc", () => {
  const actual = jest.requireActual("@/lib/projects/svc");
  return {
    ...actual,
    fetchProjects: jest.fn().mockResolvedValue([]),
    createProject: jest.fn(),
    uploadFiles: (...args: unknown[]) => mockUploadFiles(...args),
    getRecentFiles: (...args: unknown[]) => mockGetRecentFiles(...args),
    getFilesInProject: jest.fn().mockResolvedValue([]),
    getProject: jest.fn(),
    getProjectInstructions: jest.fn(),
    upsertProjectInstructions: jest.fn(),
    getProjectDetails: jest.fn(),
    renameProject: jest.fn(),
    deleteProject: jest.fn(),
    deleteUserFile: (...args: unknown[]) => mockDeleteUserFile(...args),
    getUserFileStatuses: (...args: unknown[]) =>
      mockGetUserFileStatuses(...args),
    unlinkFileFromProject: jest.fn(),
    linkFileToProject: jest.fn(),
  };
});

const wrapper = ({ children }: PropsWithChildren) => (
  <NextIntlClientProvider locale="en" messages={englishMessages}>
    <ProjectsProvider>{children}</ProjectsProvider>
  </NextIntlClientProvider>
);

describe("ProjectsContext beginUpload size precheck", () => {
  beforeEach(() => {
    mockUploadFiles.mockReset();
    mockGetRecentFiles.mockReset();
    mockToastWarning.mockReset();

    mockUploadFiles.mockResolvedValue({
      user_files: [],
      rejected_files: [],
    });
    mockGetRecentFiles.mockResolvedValue([]);
    mockGetUserFileStatuses.mockResolvedValue([]);
  });

  it("only sends valid files to the upload API when oversized files are present", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const valid = new File(["small"], "small.txt", { type: "text/plain" });
    const oversized = new File([new Uint8Array(2 * 1024 * 1024)], "big.txt", {
      type: "text/plain",
    });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [valid, oversized],
        null
      );
    });

    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    const [uploadedFiles] = mockUploadFiles.mock.calls[0];
    expect((uploadedFiles as File[]).map((f) => f.name)).toEqual(["small.txt"]);
    expect(optimisticFiles.map((f) => f.name)).toEqual(["small.txt"]);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
  });

  it("uploads all files when none are oversized", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const first = new File(["small"], "first.txt", { type: "text/plain" });
    const second = new File(["small"], "second.txt", { type: "text/plain" });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload([first, second], null);
    });

    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    const [uploadedFiles] = mockUploadFiles.mock.calls[0];
    expect((uploadedFiles as File[]).map((f) => f.name)).toEqual([
      "first.txt",
      "second.txt",
    ]);
    expect(mockToastWarning).not.toHaveBeenCalled();
    expect(optimisticFiles.map((f) => f.name)).toEqual([
      "first.txt",
      "second.txt",
    ]);
  });

  it("does not call upload API when all files are oversized", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const oversized = new File(
      [new Uint8Array(2 * 1024 * 1024)],
      "too-big.txt",
      { type: "text/plain" }
    );
    const onSuccess = jest.fn();
    const onFailure = jest.fn();

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [oversized],
        null,
        onSuccess,
        onFailure
      );
    });

    expect(mockUploadFiles).not.toHaveBeenCalled();
    expect(optimisticFiles).toEqual([]);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
    expect(onSuccess).not.toHaveBeenCalled();
    expect(onFailure).toHaveBeenCalledWith([]);
  });

  it("reports the optimistic temp id via onFailure when the server rejects a file", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    const rejected = new File(["small"], "too-many-tokens.txt", {
      type: "text/plain",
    });
    const onSuccess = jest.fn();
    const onFailure = jest.fn();

    mockUploadFiles.mockResolvedValue({
      user_files: [],
      rejected_files: [
        { file_name: "too-many-tokens.txt", reason: "Exceeds token limit" },
      ],
    });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [rejected],
        null,
        onSuccess,
        onFailure
      );
    });

    const tempId = optimisticFiles[0]?.temp_id;
    expect(tempId).toBeTruthy();
    expect(mockUploadFiles).toHaveBeenCalledTimes(1);
    expect(mockToastWarning).toHaveBeenCalledTimes(1);
    // AgentEditorPage relies on this callback firing with the failed temp id
    // to strip the file from user_file_ids; otherwise the submit button stays
    // disabled forever waiting on a phantom "uploading" file.
    expect(onFailure).toHaveBeenCalledWith([tempId]);
  });
});

describe("ProjectsContext beginUpload with files of one name", () => {
  function serverFile(id: string, tempId: string | undefined): ProjectFile {
    return {
      id,
      name: "notes.txt",
      project_id: null,
      user_id: null,
      file_id: `store-${id}`,
      created_at: "2026-01-01T00:00:00Z",
      status: UserFileStatus.PROCESSING,
      file_type: "text/plain",
      last_accessed_at: "2026-01-01T00:00:00Z",
      chat_file_type: ChatFileType.PLAIN_TEXT,
      token_count: null,
      chunk_count: null,
      temp_id: tempId,
    };
  }

  beforeEach(() => {
    mockUploadFiles.mockReset();
    mockGetRecentFiles.mockReset();
    mockToastWarning.mockReset();
    mockGetRecentFiles.mockResolvedValue([]);
    mockGetUserFileStatuses.mockResolvedValue([]);
  });

  it("gives each file its own server file by temporary ID", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });
    const first = new File(["one"], "notes.txt", { type: "text/plain" });
    const second = new File(["two"], "notes.txt", { type: "text/plain" });
    // The server answers in another order.
    mockUploadFiles.mockImplementation(
      async (_files: File[], _projectId: unknown, tempIds: string[]) => ({
        user_files: [
          serverFile("server-second", tempIds[1]),
          serverFile("server-first", tempIds[0]),
        ],
        rejected_files: [],
      })
    );

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload([first, second], null);
    });

    const tempIds = optimisticFiles.map((f) => f.temp_id);
    expect(new Set(tempIds).size).toBe(2);
    expect(mockUploadFiles.mock.calls[0]?.[2]).toEqual(tempIds);
    await waitFor(() =>
      expect(
        tempIds.map(
          (tempId) =>
            result.current.allRecentFiles.find((f) => f.temp_id === tempId)?.id
        )
      ).toEqual(["server-first", "server-second"])
    );
  });

  it("fails only the file that the server rejected", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });
    const first = new File(["one"], "notes.txt", { type: "text/plain" });
    const second = new File(["two"], "notes.txt", { type: "text/plain" });
    mockUploadFiles.mockImplementation(
      async (_files: File[], _projectId: unknown, tempIds: string[]) => ({
        user_files: [serverFile("server-second", tempIds[1])],
        rejected_files: [{ file_name: "notes.txt", reason: "Unsupported" }],
      })
    );
    const onFailure = jest.fn();

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [first, second],
        null,
        undefined,
        onFailure
      );
    });

    await waitFor(() =>
      expect(onFailure).toHaveBeenCalledWith([optimisticFiles[0]?.temp_id])
    );
  });
});

describe("ProjectsContext attached file status polling", () => {
  beforeEach(() => {
    mockGetRecentFiles.mockReset();
    mockGetUserFileStatuses.mockReset();
    mockGetUserFileStatuses.mockResolvedValue([]);
    mockGetRecentFiles.mockResolvedValue([]);
  });

  function makePendingFile(id: string): ProjectFile {
    return {
      id,
      name: `${id}.txt`,
      project_id: null,
      user_id: null,
      file_id: `store-${id}`,
      created_at: "2026-01-01T00:00:00Z",
      status: UserFileStatus.INDEXING,
      file_type: "text/plain",
      last_accessed_at: "2026-01-01T00:00:00Z",
      chat_file_type: ChatFileType.PLAIN_TEXT,
      token_count: 10,
      chunk_count: null,
    };
  }

  function completedStatuses(ids: string[]): ProjectFile[] {
    return ids.map((id) => ({
      ...makePendingFile(id),
      status: UserFileStatus.COMPLETED,
    }));
  }

  it("refreshes a pending file attached from recents until it is ready", async () => {
    const pendingFile = makePendingFile("file-1");
    mockGetUserFileStatuses.mockResolvedValue([
      { ...pendingFile, status: UserFileStatus.COMPLETED },
    ]);

    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    await act(async () => {
      result.current.setCurrentMessageFiles([pendingFile]);
    });

    await waitFor(() =>
      expect(result.current.currentMessageFiles[0]?.status).toBe(
        UserFileStatus.COMPLETED
      )
    );
    expect(mockGetUserFileStatuses).toHaveBeenCalledWith(["file-1"]);
  });

  it("does not poll a completed file, such as one from a sent message", async () => {
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    await act(async () => {
      result.current.setCurrentMessageFiles([
        { ...makePendingFile("store-id"), status: UserFileStatus.COMPLETED },
      ]);
    });

    expect(mockGetUserFileStatuses).not.toHaveBeenCalled();
    expect(result.current.currentMessageFiles).toHaveLength(1);
  });

  it("updates a pending file attached again while its status request runs", async () => {
    const pendingFile = makePendingFile("file-1");
    let resolveFirstPoll: (value: ProjectFile[]) => void = () => {};
    mockGetUserFileStatuses
      .mockImplementationOnce(
        () =>
          new Promise<ProjectFile[]>((resolve) => {
            resolveFirstPoll = resolve;
          })
      )
      .mockImplementation(async (ids: string[]) => completedStatuses(ids));
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    // A draft set aside for an edit keeps the pending copy.
    await act(async () => {
      result.current.setCurrentMessageFiles([pendingFile]);
    });
    await waitFor(() =>
      expect(mockGetUserFileStatuses).toHaveBeenCalledWith(["file-1"])
    );
    await act(async () => {
      result.current.setCurrentMessageFiles([]);
    });
    await act(async () => {
      result.current.setCurrentMessageFiles([pendingFile]);
    });
    await act(async () => {
      resolveFirstPoll(completedStatuses(["file-1"]));
    });

    await waitFor(() =>
      expect(result.current.currentMessageFiles[0]?.status).toBe(
        UserFileStatus.COMPLETED
      )
    );
  });

  it("polls a file attached while a finished poll refreshes recent files", async () => {
    let releaseRecentFiles: () => void = () => {};
    const recentFiles = new Promise<Response>((resolve) => {
      releaseRecentFiles = () => resolve(new Response("[]", { status: 200 }));
    });
    const fetchSpy = jest
      .spyOn(global, "fetch")
      .mockImplementation(() => recentFiles);
    mockGetUserFileStatuses.mockImplementation(async (ids: string[]) =>
      completedStatuses(ids)
    );
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    // The first poll finishes its file, then waits on the recent files.
    await act(async () => {
      result.current.setCurrentMessageFiles([makePendingFile("file-1")]);
    });
    await waitFor(() =>
      expect(result.current.currentMessageFiles[0]?.status).toBe(
        UserFileStatus.COMPLETED
      )
    );
    await act(async () => {
      result.current.setCurrentMessageFiles([
        ...result.current.currentMessageFiles,
        makePendingFile("file-2"),
      ]);
    });
    await act(async () => releaseRecentFiles());

    await waitFor(() =>
      expect(result.current.currentMessageFiles[1]?.status).toBe(
        UserFileStatus.COMPLETED
      )
    );
    fetchSpy.mockRestore();
  });

  it("polls a file attached during a status request right after it", async () => {
    const first = makePendingFile("file-1");
    const second = makePendingFile("file-2");
    let resolveFirstPoll: (value: ProjectFile[]) => void = () => {};
    mockGetUserFileStatuses
      .mockImplementationOnce(
        () =>
          new Promise<ProjectFile[]>((resolve) => {
            resolveFirstPoll = resolve;
          })
      )
      .mockImplementation(async (ids: string[]) => completedStatuses(ids));

    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    await act(async () => {
      result.current.setCurrentMessageFiles([first]);
    });
    await waitFor(() =>
      expect(mockGetUserFileStatuses).toHaveBeenCalledWith(["file-1"])
    );

    await act(async () => {
      result.current.setCurrentMessageFiles([first, second]);
    });
    await act(async () => {
      resolveFirstPoll(completedStatuses(["file-1"]));
    });

    await waitFor(() =>
      expect(result.current.currentMessageFiles.map((f) => f.status)).toEqual([
        UserFileStatus.COMPLETED,
        UserFileStatus.COMPLETED,
      ])
    );
  });
});

describe("ProjectsContext beginUpload cancel", () => {
  beforeEach(() => {
    mockUploadFiles.mockReset();
    mockGetRecentFiles.mockReset();
    mockToastError.mockReset();
    mockGetRecentFiles.mockResolvedValue([]);
    mockGetUserFileStatuses.mockResolvedValue([]);
  });

  it("aborts the request and shows no error toast", async () => {
    let signal: AbortSignal | undefined;
    mockUploadFiles.mockImplementation(
      (
        _files: File[],
        _projectId: number | null,
        _tempIds: string[],
        _incognito: string | null,
        options: UploadFilesOptions
      ) =>
        new Promise((_resolve, reject) => {
          signal = options.signal;
          options.signal?.addEventListener("abort", () => {
            const error = new Error("Upload cancelled");
            error.name = "AbortError";
            reject(error);
          });
        })
    );
    const { result } = renderHook(() => useProjectsContext(), { wrapper });
    const onFailure = jest.fn();

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [new File(["a"], "a.txt", { type: "text/plain" })],
        null,
        undefined,
        onFailure
      );
    });
    const tempId = optimisticFiles[0]?.temp_id ?? "";

    act(() => cancelUpload(tempId));

    expect(signal?.aborted).toBe(true);
    await waitFor(() => expect(onFailure).toHaveBeenCalledWith([tempId]));
    expect(mockToastError).not.toHaveBeenCalled();
  });
  it("deletes a file cancelled while the rest of its batch uploaded", async () => {
    let finishUpload: (value: unknown) => void = () => {};
    mockUploadFiles.mockImplementation(
      () =>
        new Promise((resolve) => {
          finishUpload = resolve;
        })
    );
    mockDeleteUserFile.mockReset();
    mockDeleteUserFile.mockResolvedValue({ deleted: true });
    const { result } = renderHook(() => useProjectsContext(), { wrapper });
    const onSuccess = jest.fn();

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [
          new File(["a"], "kept.txt", { type: "text/plain" }),
          new File(["b"], "removed.txt", { type: "text/plain" }),
        ],
        null,
        onSuccess
      );
    });
    const [kept, removed] = optimisticFiles.map((f) => f.temp_id ?? "");
    act(() => cancelUpload(removed ?? ""));
    const serverFile = (tempId: string | undefined, id: string) => ({
      ...optimisticFiles[0],
      id,
      temp_id: tempId,
      status: UserFileStatus.PROCESSING,
    });

    await act(async () => {
      finishUpload({
        user_files: [
          serverFile(kept, "user-kept"),
          serverFile(removed, "user-removed"),
        ],
        rejected_files: [],
      });
    });

    await waitFor(() =>
      expect(mockDeleteUserFile).toHaveBeenCalledWith("user-removed")
    );
    expect(mockDeleteUserFile).toHaveBeenCalledTimes(1);
    expect(result.current.allRecentFiles.map((f) => f.temp_id)).not.toContain(
      removed
    );
    expect(onSuccess).toHaveBeenCalledWith({
      user_files: [serverFile(kept, "user-kept")],
      rejected_files: [],
    });
    expect(mockToastError).not.toHaveBeenCalled();
  });
  it("deletes a file cancelled after its whole body was sent", async () => {
    let finishUpload: (value: unknown) => void = () => {};
    let uploadOptions: UploadFilesOptions = {};
    mockUploadFiles.mockImplementation(
      (
        _files: File[],
        _projectId: number | null,
        _tempIds: string[],
        _incognito: string | null,
        options: UploadFilesOptions
      ) =>
        new Promise((resolve) => {
          uploadOptions = options;
          finishUpload = resolve;
        })
    );
    mockDeleteUserFile.mockReset();
    mockDeleteUserFile.mockResolvedValue({ deleted: true });
    const { result } = renderHook(() => useProjectsContext(), { wrapper });

    let optimisticFiles: ProjectFile[] = [];
    await act(async () => {
      optimisticFiles = await result.current.beginUpload(
        [new File(["a"], "sent.txt", { type: "text/plain" })],
        null
      );
    });
    const tempId = optimisticFiles[0]?.temp_id ?? "";
    act(() => uploadOptions.onProgress?.(1));
    act(() => cancelUpload(tempId));

    expect(uploadOptions.signal?.aborted).toBe(false);
    await act(async () => {
      finishUpload({
        user_files: [
          {
            ...optimisticFiles[0],
            id: "user-sent",
            temp_id: tempId,
            status: UserFileStatus.PROCESSING,
          },
        ],
        rejected_files: [],
      });
    });

    await waitFor(() =>
      expect(mockDeleteUserFile).toHaveBeenCalledWith("user-sent")
    );
    expect(result.current.allRecentFiles.map((f) => f.temp_id)).not.toContain(
      tempId
    );
    expect(mockToastError).not.toHaveBeenCalled();
  });
});
