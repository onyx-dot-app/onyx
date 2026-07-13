import { beforeEach, describe, expect, it, jest } from "@jest/globals";
import type { Mock } from "jest-mock";
import * as React from "react";
import { act, renderHook, waitFor } from "@testing-library/react-native";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { generateTempId } from "@/api/files/upload";
import { pickDocuments } from "@/api/files/pickers";
import {
  UserFileStatus,
  type CategorizedFiles,
  type ProjectFile,
} from "@/chat/contracts/projects";
import { ChatFileType } from "@/chat/interfaces";
import { makeProjectFile } from "@/chat/__tests__/fixtures";
import { ComposerDraftProvider } from "@/components/chat/ComposerDraftProvider";
import { useComposerDraft } from "@/hooks/useComposerDraft";
import { setUploadCancel, useUserFileStore } from "@/state/userFileStore";

let mockTransportResult: Promise<CategorizedFiles>;

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
jest.mock("@/api/settings", () => ({
  useWorkspaceSettings: () => ({
    settings: {
      disable_default_assistant: false,
      user_file_max_upload_size_mb: null,
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
const generateTempIdMock = generateTempId as unknown as Mock<() => string>;

function recent(overrides: Partial<ProjectFile> = {}): ProjectFile {
  return makeProjectFile({ status: UserFileStatus.COMPLETED, ...overrides });
}

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  return (
    <QueryClientProvider client={client}>
      <ComposerDraftProvider>{children}</ComposerDraftProvider>
    </QueryClientProvider>
  );
}

describe("useComposerDraft", () => {
  beforeEach(() => {
    useUserFileStore.setState({
      filesById: {},
      serverIdToClientId: {},
      tasksById: {},
      progressById: {},
      epochCounter: 0,
    });
    jest.clearAllMocks();
    let counter = 0;
    generateTempIdMock.mockImplementation(() => `tmp-${++counter}`);
  });

  it("stores and restores the draft (text + attachments) per conversation key", () => {
    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useComposerDraft(key),
      { wrapper, initialProps: { key: "chat-1:" } },
    );
    act(() => {
      result.current.setText("hello");
      result.current.addRecent(recent({ id: "r1" }));
    });
    expect(result.current.text).toBe("hello");
    expect(result.current.files.map((f) => f.id)).toEqual(["r1"]);

    rerender({ key: "chat-2:" });
    expect(result.current.text).toBe("");
    expect(result.current.files).toEqual([]);

    rerender({ key: "chat-1:" });
    expect(result.current.text).toBe("hello");
    expect(result.current.files.map((f) => f.id)).toEqual(["r1"]);
  });

  it("uploads a picked document, reconciles, builds descriptors, and unblocks send", async () => {
    pickDocumentsMock.mockResolvedValue([
      { uri: "file:///a.pdf", name: "a.pdf", size: 10 },
    ]);
    mockTransportResult = Promise.resolve({
      user_files: [
        makeProjectFile({
          id: "u1",
          file_id: "blob-1",
          name: "a.pdf",
          temp_id: "tmp-1",
          status: UserFileStatus.COMPLETED,
          token_count: 5,
        }),
      ],
      rejected_files: [],
    });

    const { result } = renderHook(() => useComposerDraft("chat-1:"), {
      wrapper,
    });
    await act(async () => {
      await result.current.addDocuments();
    });

    await waitFor(() =>
      expect(result.current.files[0]?.file_id).toBe("blob-1"),
    );
    expect(result.current.hasBlockingFiles).toBe(false);
    expect(result.current.descriptors).toEqual([
      {
        id: "blob-1",
        type: ChatFileType.DOCUMENT,
        name: "a.pdf",
        user_file_id: "u1",
      },
    ]);
  });

  it("blocks send while an attachment is still indexing, and removing it unblocks", () => {
    const { result } = renderHook(() => useComposerDraft("chat-1:"), {
      wrapper,
    });
    act(() =>
      result.current.addRecent(
        recent({ id: "r1", status: UserFileStatus.INDEXING }),
      ),
    );
    expect(result.current.hasBlockingFiles).toBe(true);

    act(() => result.current.removeFile("r1"));
    expect(result.current.files).toEqual([]);
    expect(result.current.hasBlockingFiles).toBe(false);
  });

  it("removing a recent-attached chip de-references it without deleting the shared record", () => {
    const { result } = renderHook(() => useComposerDraft("chat-1:"), {
      wrapper,
    });
    act(() => result.current.addRecent(recent({ id: "shared" })));
    expect(result.current.files.map((f) => f.id)).toEqual(["shared"]);

    act(() => result.current.removeFile("shared"));
    // The draft drops its reference...
    expect(result.current.files).toEqual([]);
    // ...but the shared store record survives for other surfaces (recent picker, other drafts).
    expect(useUserFileStore.getState().filesById["shared"]).toBeDefined();
  });

  it("removing a recent-attached upload owned by another draft doesn't abort that upload", () => {
    // conversation 1 owns an in-flight upload (live cancel handle)
    const cancel = jest.fn();
    useUserFileStore
      .getState()
      .beginUpload({ kind: "draft", draftKey: "chat-1:" }, [
        {
          clientId: "tmp-1",
          file: recent({
            id: "tmp-1",
            temp_id: "tmp-1",
            status: UserFileStatus.UPLOADING,
          }),
        },
      ]);
    setUploadCancel("tmp-1", cancel);

    // conversation 2 recent-attaches the same still-uploading file, then removes it
    const { result } = renderHook(() => useComposerDraft("chat-2:"), {
      wrapper,
    });
    act(() =>
      result.current.addRecent(
        recent({
          id: "tmp-1",
          temp_id: "tmp-1",
          status: UserFileStatus.UPLOADING,
        }),
      ),
    );
    expect(result.current.files.map((f) => f.id)).toEqual(["tmp-1"]);

    act(() => result.current.removeFile("tmp-1"));
    expect(result.current.files).toEqual([]);
    expect(cancel).not.toHaveBeenCalled();
    expect(useUserFileStore.getState().filesById["tmp-1"]).toBeDefined();
    expect(useUserFileStore.getState().tasksById["tmp-1"]).toBeDefined();

    // owner can still cancel its own upload (also proves the handle was live)
    act(() =>
      useUserFileStore
        .getState()
        .removeFile("tmp-1", { kind: "draft", draftKey: "chat-1:" }),
    );
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it("consume clears text + attachments; consumeAttachments keeps the text", () => {
    const { result } = renderHook(() => useComposerDraft("chat-1:"), {
      wrapper,
    });
    act(() => {
      result.current.setText("keep");
      result.current.addRecent(recent({ id: "r1" }));
    });

    act(() => result.current.consumeAttachments());
    expect(result.current.text).toBe("keep");
    expect(result.current.files).toEqual([]);

    act(() => result.current.consume());
    expect(result.current.text).toBe("");
  });
});
