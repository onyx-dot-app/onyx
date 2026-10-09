import { useEffect, type ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { act, deferred, renderHook, waitFor } from "@tests/setup/test-utils";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import englishMessages from "@/i18n/messages/en.json";
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

type DirectoryListing = Awaited<ReturnType<typeof fetchDirectoryListing>>;

function listing(name: string): DirectoryListing {
  return {
    path: "attachments",
    entries: [
      {
        name,
        path: `attachments/${name}`,
        is_directory: false,
        size: 10,
        mime_type: "text/plain",
      },
    ],
  };
}

function Provider({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider locale="en" messages={englishMessages}>
      <UploadFilesProvider>{children}</UploadFilesProvider>
    </NextIntlClientProvider>
  );
}

beforeEach(() => {
  jest.resetAllMocks();
  jest.mocked(deleteFile).mockResolvedValue(undefined);
});

it("removes the old session's attachments before showing another session", async () => {
  const second = deferred<DirectoryListing>();
  jest
    .mocked(fetchDirectoryListing)
    .mockImplementation((sessionId) =>
      sessionId === "session-a"
        ? Promise.resolve(listing("a.txt"))
        : second.promise
    );
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles).toHaveLength(1)
  );
  act(() => result.current.setActiveSession("session-b"));
  expect(result.current.currentMessageFiles).toEqual([]);
  await act(async () => second.resolve(listing("b.txt")));
  await waitFor(() =>
    expect(result.current.currentMessageFiles.map((file) => file.path)).toEqual(
      ["attachments/b.txt"]
    )
  );
  expect(deleteFile).not.toHaveBeenCalled();
});

it("rejects an earlier session's attachment response after a later session is active", async () => {
  const first = deferred<DirectoryListing>();
  jest
    .mocked(fetchDirectoryListing)
    .mockImplementation((sessionId) =>
      sessionId === "session-a"
        ? first.promise
        : Promise.resolve(listing("b.txt"))
    );
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  act(() => result.current.setActiveSession("session-b"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles.map((file) => file.path)).toEqual(
      ["attachments/b.txt"]
    )
  );
  await act(async () => first.resolve(listing("private-a.txt")));
  expect(result.current.activeSessionId).toBe("session-b");
  expect(result.current.currentMessageFiles.map((file) => file.path)).toEqual([
    "attachments/b.txt",
  ]);
});

it("rejects an earlier response after leaving and returning to the same session", async () => {
  const first = deferred<DirectoryListing>();
  jest
    .mocked(fetchDirectoryListing)
    .mockReturnValueOnce(first.promise)
    .mockResolvedValueOnce(listing("b.txt"))
    .mockResolvedValueOnce(listing("new-a.txt"));
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  act(() => result.current.setActiveSession("session-b"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles.map((file) => file.path)).toEqual(
      ["attachments/b.txt"]
    )
  );
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles.map((file) => file.path)).toEqual(
      ["attachments/new-a.txt"]
    )
  );
  await act(async () => first.resolve(listing("old-a.txt")));
  expect(result.current.activeSessionId).toBe("session-a");
  expect(result.current.currentMessageFiles.map((file) => file.path)).toEqual([
    "attachments/new-a.txt",
  ]);
});

it("uploads pending welcome files once when a session becomes available", async () => {
  jest
    .mocked(fetchDirectoryListing)
    .mockResolvedValue({ path: "attachments", entries: [] });
  jest.mocked(uploadFile).mockResolvedValue({
    path: "attachments/welcome.txt",
    filename: "welcome.txt",
    size_bytes: 7,
  });
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  const file = new File(["welcome"], "welcome.txt", { type: "text/plain" });
  await act(async () => {
    await result.current.uploadFiles([file]);
  });
  expect(result.current.currentMessageFiles[0]?.status).toBe(
    UploadFileStatus.PENDING
  );
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles[0]?.status).toBe(
      UploadFileStatus.COMPLETED
    )
  );
  expect(uploadFile).toHaveBeenCalledTimes(1);
  expect(uploadFile).toHaveBeenCalledWith("session-a", file);
  expect(result.current.currentMessageFiles[0]?.file).toBeUndefined();
});

it("rejects upload completion from a previous visit to the session", async () => {
  const upload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
  jest
    .mocked(fetchDirectoryListing)
    .mockResolvedValue({ path: "attachments", entries: [] });
  jest.mocked(uploadFile).mockReturnValue(upload.promise);
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  let pending: Promise<unknown> | undefined;
  act(() => {
    pending = result.current.uploadFiles([
      new File(["private"], "private.txt"),
    ]);
  });
  act(() => result.current.setActiveSession("session-b"));
  act(() => result.current.setActiveSession("session-a"));
  await act(async () => {
    upload.resolve({
      path: "attachments/private.txt",
      filename: "private.txt",
      size_bytes: 7,
    });
    await pending;
  });
  expect(result.current.currentMessageFiles).toEqual([]);
});

it("uses the same completion flow for immediate upload success and failure", async () => {
  jest
    .mocked(fetchDirectoryListing)
    .mockResolvedValue({ path: "attachments", entries: [] });
  jest
    .mocked(uploadFile)
    .mockResolvedValueOnce({
      path: "attachments/ok.txt",
      filename: "ok.txt",
      size_bytes: 2,
    })
    .mockRejectedValueOnce(new Error("network unavailable"));
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  await act(async () => {
    await result.current.uploadFiles([
      new File(["ok"], "ok.txt"),
      new File(["bad"], "bad.txt"),
    ]);
  });
  expect(result.current.currentMessageFiles.map((file) => file.status)).toEqual(
    [UploadFileStatus.COMPLETED, UploadFileStatus.FAILED]
  );
  expect(result.current.currentMessageFiles[0]?.file).toBeUndefined();
  expect(result.current.currentMessageFiles[1]?.error).toBeTruthy();
});

it("removes files in one batch without refetching or repeating a deletion", async () => {
  jest.mocked(fetchDirectoryListing).mockResolvedValue({
    path: "attachments",
    entries: [...listing("a.txt").entries, ...listing("b.txt").entries],
  });
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles).toHaveLength(2)
  );
  const files = result.current.currentMessageFiles;
  await act(async () => {
    for (const file of files) {
      result.current.removeFile(file.id);
      result.current.removeFile(file.id);
    }
  });
  expect(result.current.currentMessageFiles).toEqual([]);
  expect(deleteFile).toHaveBeenCalledTimes(2);
  expect(fetchDirectoryListing).toHaveBeenCalledTimes(1);
});

it("rejects a deletion rollback after leaving and returning to its session", async () => {
  const deletion = deferred<void>();
  jest.mocked(deleteFile).mockReturnValue(deletion.promise);
  jest
    .mocked(fetchDirectoryListing)
    .mockResolvedValueOnce(listing("old.txt"))
    .mockResolvedValue({ path: "attachments", entries: [] });
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles).toHaveLength(1)
  );
  const file = result.current.currentMessageFiles[0];
  if (!file) throw new Error("Attachment missing");
  act(() => result.current.removeFile(file.id));
  expect(deleteFile).toHaveBeenCalledWith("session-a", "attachments/old.txt");
  act(() => result.current.setActiveSession("session-b"));
  act(() => result.current.setActiveSession("session-a"));
  await act(async () => deletion.reject(new Error("network unavailable")));
  expect(result.current.currentMessageFiles).toEqual([]);
});

it("rejects captured actions from an earlier visit to the same session", async () => {
  jest.mocked(fetchDirectoryListing).mockResolvedValue(listing("current.txt"));
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  const oldActions = result.current;
  act(() => result.current.setActiveSession("session-b"));
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles[0]?.name).toBe("current.txt")
  );
  const current = result.current.currentMessageFiles[0];
  if (!current) throw new Error("Attachment missing");
  await act(async () => {
    oldActions.removeFile(current.id);
    oldActions.clearFiles();
    await oldActions.uploadFiles([new File(["private"], "private.txt")]);
  });
  expect(result.current.currentMessageFiles).toEqual([current]);
  expect(uploadFile).not.toHaveBeenCalled();
  expect(deleteFile).not.toHaveBeenCalled();
});

it("fetches the new session scope after switching away and back in one batch", async () => {
  jest
    .mocked(fetchDirectoryListing)
    .mockResolvedValueOnce(listing("old.txt"))
    .mockResolvedValueOnce(listing("current.txt"));
  const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
  act(() => result.current.setActiveSession("session-a"));
  await waitFor(() =>
    expect(result.current.currentMessageFiles[0]?.name).toBe("old.txt")
  );
  act(() => {
    result.current.setActiveSession("session-b");
    result.current.setActiveSession("session-a");
  });
  await waitFor(() =>
    expect(result.current.currentMessageFiles[0]?.name).toBe("current.txt")
  );
  expect(fetchDirectoryListing).toHaveBeenCalledTimes(2);
});

it.each(["upload", "delete"])(
  "invalidates the original Files cache after a delayed %s completes in another session",
  async (operation) => {
    const store = useBuildSessionStore.getState();
    store.createSession("mutation-a");
    store.createSession("mutation-b");
    const generation =
      useBuildSessionStore.getState().sessions.get("mutation-a")
        ?.filesNeedsRefresh ?? 0;
    const upload = deferred<Awaited<ReturnType<typeof uploadFile>>>();
    const deletion = deferred<void>();
    jest.mocked(uploadFile).mockReturnValue(upload.promise);
    jest.mocked(deleteFile).mockReturnValue(deletion.promise);
    jest
      .mocked(fetchDirectoryListing)
      .mockImplementation(async (id) =>
        listing(id === "mutation-a" ? "a.txt" : "b.txt")
      );
    const { result } = renderHook(useUploadFilesContext, { wrapper: Provider });
    act(() => result.current.setActiveSession("mutation-a"));
    await waitFor(() =>
      expect(result.current.currentMessageFiles[0]?.name).toBe("a.txt")
    );
    let pending: Promise<unknown> | undefined;
    act(() => {
      if (operation === "upload")
        pending = result.current.uploadFiles([new File(["new"], "new.txt")]);
      else {
        const file = result.current.currentMessageFiles[0];
        if (!file) throw new Error("Attachment missing");
        result.current.removeFile(file.id);
      }
    });
    act(() => result.current.setActiveSession("mutation-b"));
    await waitFor(() =>
      expect(result.current.currentMessageFiles[0]?.name).toBe("b.txt")
    );
    await act(async () => {
      if (operation === "upload") {
        upload.resolve({
          path: "attachments/new.txt",
          filename: "new.txt",
          size_bytes: 3,
        });
        await pending;
      } else deletion.resolve();
    });
    expect(result.current.currentMessageFiles.map((file) => file.name)).toEqual(
      ["b.txt"]
    );
    expect(
      useBuildSessionStore.getState().sessions.get("mutation-a")
        ?.filesNeedsRefresh
    ).toBe(generation + 1);
    expect(
      useBuildSessionStore.getState().sessions.get("mutation-b")
        ?.filesNeedsRefresh
    ).toBe(0);
  }
);

it("rejects a listing from before the chat unmounted and revisited its session", async () => {
  const previousVisit = deferred<DirectoryListing>();
  jest
    .mocked(fetchDirectoryListing)
    .mockReturnValueOnce(previousVisit.promise)
    .mockResolvedValueOnce(listing("current.txt"));
  const { result, rerender } = renderHook(
    ({ mounted }) => {
      const context = useUploadFilesContext();
      useEffect(() => {
        if (!mounted) return;
        context.setActiveSession("session-a");
        return () => context.setActiveSession(null);
      }, [mounted, context.setActiveSession]);
      return context;
    },
    { initialProps: { mounted: true }, wrapper: Provider }
  );
  await waitFor(() => expect(fetchDirectoryListing).toHaveBeenCalledTimes(1));
  rerender({ mounted: false });
  rerender({ mounted: true });
  await waitFor(() =>
    expect(result.current.currentMessageFiles[0]?.name).toBe("current.txt")
  );
  await act(async () => previousVisit.resolve(listing("stale.txt")));
  expect(result.current.currentMessageFiles.map((file) => file.name)).toEqual([
    "current.txt",
  ]);
});
