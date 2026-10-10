import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { act, deferred, renderHook, waitFor } from "@tests/setup/test-utils";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import englishMessages from "@/i18n/messages/en.json";
import { FetchError } from "@/lib/fetcher";
import {
  UploadFilesProvider,
  useUploadFilesContext,
  UploadFileStatus,
} from "@/app/craft/contexts/UploadFilesContext";
import {
  fetchDirectoryListing,
  deleteFile,
  uploadFile,
} from "@/app/craft/services/apiServices";

jest.mock("@/app/craft/services/apiServices", () => ({
  fetchDirectoryListing: jest.fn(),
  deleteFile: jest.fn(),
  uploadFile: jest.fn(),
}));

function Provider({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <UploadFilesProvider>{children}</UploadFilesProvider>
    </NextIntlClientProvider>
  );
}

const response = {
  path: "attachments/draft.txt",
  filename: "draft.txt",
  size_bytes: 5,
};

beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(uploadFile).mockResolvedValue(response);
});

it("starts an existing session with an empty draft, without reading persisted files", async () => {
  jest.mocked(fetchDirectoryListing).mockResolvedValue({
    path: "attachments",
    entries: [
      {
        name: "history.txt",
        path: "attachments/history.txt",
        is_directory: false,
        size: 5,
        mime_type: "text/plain",
      },
    ],
  });
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("existing"));
  await act(async () => {});
  expect(result.current.currentMessageFiles).toEqual([]);
  expect(fetchDirectoryListing).not.toHaveBeenCalled();
});

it("retains the selected source after uploading and deselects without deleting history", async () => {
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  const file = new File(["draft"], "draft.txt");
  act(() => result.current.setActiveSession("session"));
  await act(async () => result.current.uploadFiles([file]));
  const selected = result.current.currentMessageFiles[0];
  expect(selected).toMatchObject({
    status: UploadFileStatus.COMPLETED,
    path: response.path,
    file,
  });
  if (!selected) throw new Error("Expected a selected file");
  act(() => result.current.removeFile(selected.id));
  expect(result.current.currentMessageFiles).toEqual([]);
  expect(deleteFile).not.toHaveBeenCalled();
  expect(fetchDirectoryListing).not.toHaveBeenCalled();
});

it.each(["remove", "send"])(
  "does not reattach an upload that completes after %s",
  async (action) => {
    const upload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
    jest.mocked(uploadFile).mockReturnValue(upload.promise);
    const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
    const refresh = jest.spyOn(
      useBuildSessionStore.getState(),
      "triggerFilesRefresh"
    );
    act(() => result.current.setActiveSession("session"));
    let pending: Promise<unknown> | undefined;
    act(() => {
      pending = result.current.uploadFiles([new File(["draft"], "draft.txt")]);
    });
    const selected = result.current.currentMessageFiles[0];
    if (!selected) throw new Error("Expected a selected file");
    act(() => {
      if (action === "remove") result.current.removeFile(selected.id);
      else result.current.clearFiles();
    });
    expect(result.current.getCurrentMessageFiles()).toEqual([]);
    await act(async () => {
      upload.resolve(response);
      await pending;
    });
    expect(result.current.currentMessageFiles).toEqual([]);
    expect(refresh).toHaveBeenCalledWith("session");
    expect(deleteFile).not.toHaveBeenCalled();
    refresh.mockRestore();
  }
);

it("clears sent selections while retaining sandbox files, including after revisiting", async () => {
  const { result, rerender } = renderHook(useUploadFilesContext, {
    wrapper: Provider,
  });
  act(() => result.current.setActiveSession("session"));
  await act(async () =>
    result.current.uploadFiles([new File(["draft"], "draft.txt")])
  );
  act(() => result.current.clearFiles());
  rerender();
  act(() => result.current.endSessionVisit());
  act(() => result.current.setActiveSession("session"));
  await act(async () => {});
  expect(result.current.currentMessageFiles).toEqual([]);
  expect(deleteFile).not.toHaveBeenCalled();
  expect(fetchDirectoryListing).not.toHaveBeenCalled();
});

it("uploads pending welcome sources once when a destination becomes available", async () => {
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  const file = new File(["draft"], "draft.txt");
  await act(async () => result.current.uploadFiles([file]));
  expect(result.current.currentMessageFiles[0]?.status).toBe(
    UploadFileStatus.PENDING
  );
  act(() => result.current.setActiveSession("sandbox", { draftId: null }));
  await waitFor(() =>
    expect(result.current.currentMessageFiles[0]?.status).toBe(
      UploadFileStatus.COMPLETED
    )
  );
  act(() => result.current.setActiveSession("sandbox", { draftId: null }));
  expect(uploadFile).toHaveBeenCalledTimes(1);
  expect(uploadFile).toHaveBeenCalledWith("sandbox", file);
});

it.each([false, true])(
  "reuploads the same welcome draft in a replacement sandbox (completed: %s)",
  async (completed) => {
    const oldUpload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
    jest
      .mocked(uploadFile)
      .mockReturnValueOnce(oldUpload.promise)
      .mockResolvedValue({ ...response, path: "attachments/replacement.txt" });
    const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
    const file = new File(["draft"], "draft.txt");
    await act(async () => result.current.uploadFiles([file]));
    act(() => result.current.setActiveSession("old", { draftId: null }));
    await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
    if (completed) await act(async () => oldUpload.resolve(response));
    act(() => result.current.setActiveSession(null, { draftId: null }));
    expect(result.current.currentMessageFiles[0]).toMatchObject({
      file,
      status: UploadFileStatus.PENDING,
    });
    expect(result.current.currentMessageFiles[0]?.path).toBeUndefined();
    act(() =>
      result.current.setActiveSession("replacement", { draftId: null })
    );
    await waitFor(() =>
      expect(result.current.currentMessageFiles[0]?.path).toBe(
        "attachments/replacement.txt"
      )
    );
    expect(uploadFile).toHaveBeenLastCalledWith("replacement", file);
    if (!completed) await act(async () => oldUpload.resolve(response));
    expect(result.current.currentMessageFiles[0]?.path).toBe(
      "attachments/replacement.txt"
    );
  }
);

it("claims the same welcome sandbox without clearing sources or uploading twice", async () => {
  const upload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
  jest.mocked(uploadFile).mockReturnValue(upload.promise);
  const { result, rerender } = renderHook(useUploadFilesContext, {
    wrapper: Provider,
  });
  const file = new File(["draft"], "draft.txt");
  await act(async () => result.current.uploadFiles([file]));
  act(() => result.current.setActiveSession("sandbox", { draftId: null }));
  await waitFor(() => expect(uploadFile).toHaveBeenCalledTimes(1));
  rerender();
  act(() => result.current.setActiveSession("sandbox", { draftId: null }));
  act(() => result.current.setActiveSession("sandbox", { draftId: "sandbox" }));
  await act(async () => upload.resolve(response));
  expect(result.current.currentMessageFiles[0]).toMatchObject({
    file,
    status: UploadFileStatus.COMPLETED,
  });
  expect(uploadFile).toHaveBeenCalledTimes(1);
});

it.each(["welcome", "existing"])(
  "starts New Build with no prior selections (%s destination)",
  async (destination) => {
    const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
    act(() => result.current.setActiveSession("existing"));
    await act(async () =>
      result.current.uploadFiles([new File(["draft"], "draft.txt")])
    );
    act(() => result.current.setActiveSession(destination, { draftId: null }));
    await act(async () => {});
    expect(result.current.currentMessageFiles).toEqual([]);
    expect(uploadFile).toHaveBeenCalledTimes(1);
  }
);

it("does not carry a pending welcome draft into an unrelated saved session", async () => {
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  await act(async () =>
    result.current.uploadFiles([new File(["draft"], "draft.txt")])
  );
  act(() => result.current.setActiveSession("saved", { draftId: "saved" }));
  await act(async () => {});
  expect(result.current.currentMessageFiles).toEqual([]);
  expect(uploadFile).not.toHaveBeenCalled();
});

it.each(["send", "end"])(
  "releases welcome sources after %s",
  async (action) => {
    const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
    await act(async () =>
      result.current.uploadFiles([new File(["draft"], "draft.txt")])
    );
    act(() => {
      if (action === "send") result.current.clearFiles();
      else result.current.endSessionVisit();
    });
    act(() =>
      result.current.setActiveSession("replacement", { draftId: null })
    );
    await act(async () => {});
    expect(result.current.currentMessageFiles).toEqual([]);
    expect(uploadFile).not.toHaveBeenCalled();
  }
);

it("rejects stale actions and an old upload after returning to the same session", async () => {
  const upload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
  jest.mocked(uploadFile).mockReturnValue(upload.promise);
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("a"));
  const old = result.current;
  let pending: Promise<unknown> | undefined;
  act(() => {
    pending = result.current.uploadFiles([new File(["old"], "old.txt")]);
  });
  act(() => result.current.setActiveSession("b"));
  act(() => result.current.setActiveSession("a"));
  jest.mocked(uploadFile).mockResolvedValue(response);
  await act(async () =>
    result.current.uploadFiles([new File(["new"], "new.txt")])
  );
  const current = result.current.currentMessageFiles;
  const currentFile = current[0];
  if (!currentFile) throw new Error("Expected a selected file");
  act(() => {
    old.clearFiles();
    old.removeFile(currentFile.id);
  });
  await act(async () => {
    await old.uploadFiles([new File(["stale"], "stale.txt")]);
    upload.resolve(response);
    await pending;
  });
  expect(result.current.currentMessageFiles).toEqual(current);
  expect(uploadFile).toHaveBeenCalledTimes(2);
});

it("publishes accepted selections synchronously for send-time reads", async () => {
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => {
    void result.current.uploadFiles([new File(["draft"], "draft.txt")]);
    expect(result.current.getCurrentMessageFiles()[0]?.status).toBe(
      UploadFileStatus.PENDING
    );
    result.current.clearFiles();
    expect(result.current.getCurrentMessageFiles()).toEqual([]);
  });
});

it.each([401, 402])(
  "classifies HTTP %s without confusing subscription and authentication",
  async (status) => {
    jest
      .mocked(uploadFile)
      .mockRejectedValue(new FetchError("Subscription inactive", status, null));
    const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
    act(() => result.current.setActiveSession("session"));
    await act(async () =>
      result.current.uploadFiles([new File(["draft"], "draft.txt")])
    );
    expect(result.current.currentMessageFiles[0]?.error).toBe(
      status === 401
        ? englishMessages.craft.uploadFiles.errors.sessionExpired
        : "Subscription inactive"
    );
  }
);
