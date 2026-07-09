import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import { act, renderHook, waitFor } from "@testing-library/react-native";

import { getUserFileStatuses } from "@/api/files/files";
import { uploadUserFile } from "@/api/files/upload";
import { pickDocuments, pickImages } from "@/api/files/pickers";
import {
  UserFileStatus,
  type CategorizedFiles,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { useMessageAttachments } from "@/hooks/useMessageAttachments";

// `jest.mock` is hoisted above the imports by babel-jest.
const mockSettingsRef = { maxMb: null as number | null };

jest.mock("@/api/files/pickers", () => ({
  pickDocuments: jest.fn(),
  pickImages: jest.fn(),
}));
jest.mock("@/api/files/upload", () => {
  let counter = 0;
  return {
    uploadUserFile: jest.fn(),
    generateTempId: () => `tmp-${++counter}`,
  };
});
jest.mock("@/api/files/files", () => ({
  getUserFileStatuses: jest.fn(),
}));
jest.mock("@/api/settings", () => ({
  useWorkspaceSettings: () => ({
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: mockSettingsRef.maxMb,
    },
  }),
}));

const pickDocumentsMock = pickDocuments as unknown as Mock<
  () => Promise<{ uri: string; name: string; size?: number }[]>
>;
const pickImagesMock = pickImages as unknown as Mock<
  () => Promise<{ uri: string; name: string; size?: number }[]>
>;
const uploadMock = uploadUserFile as unknown as Mock<
  (...args: unknown[]) => Promise<CategorizedFiles>
>;
const statusesMock = getUserFileStatuses as unknown as Mock<
  (ids: string[]) => Promise<ProjectFile[]>
>;

function serverFile(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return makeProjectFile({ name: "server.pdf", token_count: 9, ...overrides });
}

describe("useMessageAttachments", () => {
  beforeEach(() => {
    mockSettingsRef.maxMb = null;
    jest.clearAllMocks();
  });

  it("uploads a picked document, reconciles the optimistic entry, and builds descriptors", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1000 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [
        serverFile({
          id: "user-9",
          file_id: "blob-9",
          temp_id: "tmp-1",
          status: UserFileStatus.COMPLETED,
        }),
      ],
      rejected_files: [],
    });

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));

    await act(async () => {
      await result.current.addDocuments();
    });

    // per-message upload sends no project id
    expect(uploadMock).toHaveBeenCalledWith(
      { uri: "file:///a.pdf", name: "a.pdf", size: 1000 },
      null,
      expect.any(String),
      expect.any(Function),
    );
    expect(result.current.files).toHaveLength(1);
    expect(result.current.files[0].file_id).toBe("blob-9");
    expect(result.current.progressById.size).toBe(0);
    expect(result.current.descriptors).toEqual([
      {
        id: "blob-9",
        type: ChatFileType.DOCUMENT,
        name: "server.pdf",
        user_file_id: "user-9",
      },
    ]);
    expect(result.current.hasBlockingFiles).toBe(false);
  });

  it("blocks send while an attachment is still indexing", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [
        serverFile({ temp_id: "tmp-1", status: UserFileStatus.INDEXING }),
      ],
      rejected_files: [],
    });

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addDocuments();
    });

    expect(result.current.hasBlockingFiles).toBe(true);
  });

  it("blocks send on a failed upload until it is removed", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [
        serverFile({
          id: "u1",
          temp_id: "tmp-1",
          status: UserFileStatus.FAILED,
        }),
      ],
      rejected_files: [],
    });

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addDocuments();
    });
    expect(result.current.hasBlockingFiles).toBe(true);

    act(() => {
      result.current.removeFile("u1");
    });
    expect(result.current.files).toHaveLength(0);
    expect(result.current.hasBlockingFiles).toBe(false);
  });

  it("blocks oversized files with the size pre-check and never uploads them", async () => {
    mockSettingsRef.maxMb = 1;
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///big.pdf", name: "big.pdf", size: 5 * 1024 * 1024 },
    ]);

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addDocuments();
    });

    expect(uploadMock).not.toHaveBeenCalled();
    expect(result.current.errors[0]).toContain("big.pdf");
    expect(result.current.files).toHaveLength(0);
  });

  it("drops the optimistic entry and surfaces the reason when the backend rejects it", async () => {
    pickImagesMock.mockResolvedValue([
      { uri: "file:///x.heic", name: "x.heic", size: 10 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [],
      rejected_files: [
        { file_name: "x.heic", reason: "Unsupported file type" },
      ],
    });

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addImages();
    });

    expect(result.current.files).toHaveLength(0);
    expect(result.current.errors[0]).toContain("Unsupported file type");
  });

  it("attaches an already-indexed recent file and dedupes by id", () => {
    const recent = serverFile({
      id: "recent-1",
      status: UserFileStatus.COMPLETED,
    });
    const { result } = renderHook(() => useMessageAttachments("chat-1:"));

    act(() => {
      result.current.addRecent(recent);
      result.current.addRecent(recent); // no duplicate
    });

    expect(result.current.files).toHaveLength(1);
    expect(result.current.descriptors[0].user_file_id).toBe("recent-1");
  });

  it("clear() empties the draft", () => {
    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    act(() => {
      result.current.addRecent(serverFile({ id: "r1" }));
    });
    expect(result.current.files).toHaveLength(1);

    act(() => {
      result.current.clear();
    });
    expect(result.current.files).toHaveLength(0);
  });

  it("resets the draft when the conversation key changes", () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useMessageAttachments(key),
      { initialProps: { key: "chat-1:" } },
    );
    act(() => {
      result.current.addRecent(serverFile({ id: "r1" }));
    });
    expect(result.current.files).toHaveLength(1);

    rerender({ key: "chat-2:" });
    expect(result.current.files).toHaveLength(0);
  });

  it("does not resurrect an upload that resolves after the conversation switched", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1 },
    ]);
    let resolveUpload: (value: CategorizedFiles) => void = () => {};
    uploadMock.mockReturnValue(
      new Promise<CategorizedFiles>((resolve) => {
        resolveUpload = resolve;
      }),
    );

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useMessageAttachments(key),
      { initialProps: { key: "chat-1:" } },
    );

    // Start the upload; wait for the optimistic entry to land under chat-1.
    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.addDocuments();
    });
    await waitFor(() => expect(result.current.files).toHaveLength(1));

    // Switch conversations while the upload is in flight, then let it land.
    rerender({ key: "chat-2:" });
    expect(result.current.files).toHaveLength(0); // draft reset on switch
    await act(async () => {
      resolveUpload({
        user_files: [serverFile({ temp_id: "tmp-1" })],
        rejected_files: [],
      });
      await pending;
    });

    // The late reconcile is dropped (guarded by the captured conversation key).
    expect(result.current.files).toHaveLength(0);
  });

  it("polls processing files and patches their status", async () => {
    jest.useFakeTimers();
    try {
      const indexing = serverFile({
        id: "u1",
        file_id: "blob-1",
        status: UserFileStatus.INDEXING,
      });
      const { result } = renderHook(() => useMessageAttachments("chat-1:"));
      act(() => {
        result.current.addRecent(indexing);
      });
      expect(result.current.hasBlockingFiles).toBe(true);

      statusesMock.mockResolvedValue([
        serverFile({
          id: "u1",
          file_id: "blob-1",
          status: UserFileStatus.COMPLETED,
        }),
      ]);

      await act(async () => {
        jest.advanceTimersByTime(3000);
      });
      await waitFor(() => expect(result.current.hasBlockingFiles).toBe(false));
      expect(statusesMock).toHaveBeenCalledWith(["u1"]);
    } finally {
      jest.useRealTimers();
    }
  });

  it("drops the optimistic entry and surfaces an error when the upload throws", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1 },
    ]);
    uploadMock.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addDocuments();
    });

    expect(result.current.files).toHaveLength(0);
    expect(result.current.errors[0]).toContain("could not be uploaded");
    expect(result.current.hasBlockingFiles).toBe(false);
  });

  it("surfaces a picker failure inline and attempts no upload", async () => {
    pickDocumentsMock.mockRejectedValue(new Error("permission denied"));

    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addDocuments();
    });

    expect(uploadMock).not.toHaveBeenCalled();
    expect(result.current.errors).toHaveLength(1);
    expect(result.current.files).toHaveLength(0);
  });

  it("clears prior errors at the start of a fresh pick batch", async () => {
    mockSettingsRef.maxMb = 1;
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///big.pdf", name: "big.pdf", size: 5 * 1024 * 1024 },
    ]);
    const { result } = renderHook(() => useMessageAttachments("chat-1:"));
    await act(async () => {
      await result.current.addDocuments();
    });
    expect(result.current.errors).toHaveLength(1); // oversized rejection

    // A new pick starts clean — the stale rejection must not persist/stack.
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///ok.pdf", name: "ok.pdf", size: 10 },
    ]);
    uploadMock.mockResolvedValue({
      user_files: [
        serverFile({ temp_id: "tmp-1", status: UserFileStatus.COMPLETED }),
      ],
      rejected_files: [],
    });
    await act(async () => {
      await result.current.addDocuments();
    });
    expect(result.current.errors).toHaveLength(0);
  });

  it("does not leak an upload error into a conversation the user already left", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 1 },
    ]);
    let rejectUpload: (reason?: unknown) => void = () => {};
    uploadMock.mockReturnValue(
      new Promise<CategorizedFiles>((_resolve, reject) => {
        rejectUpload = reject;
      }),
    );

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useMessageAttachments(key),
      { initialProps: { key: "chat-1:" } },
    );

    let pending: Promise<void> = Promise.resolve();
    act(() => {
      pending = result.current.addDocuments();
    });
    await waitFor(() => expect(result.current.files).toHaveLength(1));

    // Leave chat-1 mid-upload, then let the upload fail. The failure belongs to a
    // conversation the user left, so the ownership guard must drop the error write.
    rerender({ key: "chat-2:" });
    await act(async () => {
      rejectUpload(new Error("network down"));
      await pending;
    });

    expect(result.current.errors).toHaveLength(0);
    expect(result.current.files).toHaveLength(0);
  });
});
