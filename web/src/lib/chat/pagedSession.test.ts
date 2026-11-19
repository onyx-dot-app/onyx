import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";
import { loadSelectedBranch } from "@/lib/chat/pagedSession";

const SESSION = "branch-session";

function pageSwitch(): number | null | undefined {
  return useChatSessionStore.getState().sessions.get(SESSION)?.latestPageSwitch;
}

function deferred(): {
  promise: Promise<Response>;
  resolve: (response: Response) => void;
} {
  let resolve: (response: Response) => void = () => undefined;
  const promise = new Promise<Response>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const page = new Response(
  JSON.stringify({ messages: [], packets: [], published_files: [] }),
  { status: 200 }
);

beforeEach(() => {
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: SESSION,
  });
  useChatSessionStore.getState().createSession(SESSION);
  jest.spyOn(console, "error").mockImplementation(() => undefined);
});

afterEach(() => jest.restoreAllMocks());

describe("loadSelectedBranch", () => {
  test("marks the page pending until the reload ends", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(page.clone());
    const save = deferred();
    const loading = loadSelectedBranch(SESSION, save.promise, true);
    expect(pageSwitch()).not.toBeNull();

    save.resolve(new Response(null, { status: 200 }));
    await expect(loading).resolves.toBe(true);
    expect(pageSwitch()).toBeNull();
  });

  test("a switch to loaded messages takes only the page's files", async () => {
    const file = {
      file_id: "subagent",
      name: "notes.md",
      title: null,
      path: "/w/notes.md",
      display_path: "notes.md",
      size: 10,
      mime_type: "text/markdown",
      message_id: 6,
    };
    jest.spyOn(global, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          messages: [],
          packets: [],
          published_files: [file],
        }),
        { status: 200 }
      )
    );
    const treeBefore = useChatSessionStore
      .getState()
      .sessions.get(SESSION)?.messageTree;
    const loading = loadSelectedBranch(
      SESSION,
      Promise.resolve(new Response(null, { status: 200 })),
      false
    );
    expect(pageSwitch()).not.toBeNull();

    await expect(loading).resolves.toBe(true);
    const session = useChatSessionStore.getState().sessions.get(SESSION);
    expect(pageSwitch()).toBeNull();
    expect(session?.branchPublishedFiles?.files).toEqual([file]);
    expect(session?.messageTree).toBe(treeBefore);
  });

  test("clears the mark when the server refuses the branch", async () => {
    await expect(
      loadSelectedBranch(
        SESSION,
        Promise.resolve(new Response(null, { status: 500 })),
        true
      )
    ).resolves.toBe(false);
    expect(pageSwitch()).toBeNull();
  });

  test("a switch whose page never applies drops the old branch's file list", async () => {
    useChatSessionStore.getState().updateSessionData(SESSION, {
      branchPublishedFiles: { files: [], throughMessageId: 7 },
    });
    await loadSelectedBranch(
      SESSION,
      Promise.resolve(new Response(null, { status: 500 })),
      true
    );
    expect(
      useChatSessionStore.getState().sessions.get(SESSION)?.branchPublishedFiles
    ).toBeNull();
  });

  test("clears the mark when the save or the reload throws", async () => {
    await expect(
      loadSelectedBranch(SESSION, Promise.reject(new Error("offline")), true)
    ).rejects.toThrow("offline");
    expect(pageSwitch()).toBeNull();

    jest.spyOn(global, "fetch").mockRejectedValue(new Error("offline"));
    await loadSelectedBranch(
      SESSION,
      Promise.resolve(new Response(null, { status: 200 })),
      true
    );
    expect(pageSwitch()).toBeNull();
  });

  test("only the newest of two quick switches clears the mark", async () => {
    jest.spyOn(global, "fetch").mockImplementation(async () => page.clone());
    const first = deferred();
    const second = deferred();
    const firstLoading = loadSelectedBranch(SESSION, first.promise, true);
    const secondLoading = loadSelectedBranch(SESSION, second.promise, true);

    first.resolve(new Response(null, { status: 200 }));
    await firstLoading;
    expect(pageSwitch()).not.toBeNull();

    second.resolve(new Response(null, { status: 200 }));
    await secondLoading;
    expect(pageSwitch()).toBeNull();
  });

  test("a newer switch discards the page of an older one", async () => {
    const files = (fileId: string) => [
      {
        file_id: fileId,
        name: "notes.md",
        title: null,
        path: "/w/notes.md",
        display_path: "notes.md",
        size: 10,
        mime_type: "text/markdown",
        message_id: 6,
      },
    ];
    const pages = [deferred(), deferred()];
    // Each resolves when its page request starts.
    const started = pages.map(() => {
      let start: () => void = () => undefined;
      const promise = new Promise<void>((done) => {
        start = done;
      });
      return { promise, start };
    });
    jest
      .spyOn(global, "fetch")
      .mockImplementationOnce(() => {
        started[0]!.start();
        return pages[0]!.promise;
      })
      .mockImplementationOnce(() => {
        started[1]!.start();
        return pages[1]!.promise;
      });
    const saved = () => Promise.resolve(new Response(null, { status: 200 }));
    const firstLoading = loadSelectedBranch(SESSION, saved(), false);
    // Both pages are loading when the second switch starts.
    await started[0]!.promise;
    const secondLoading = loadSelectedBranch(SESSION, saved(), false);
    await started[1]!.promise;

    const page = (fileId: string) =>
      new Response(
        JSON.stringify({
          messages: [],
          packets: [],
          published_files: files(fileId),
        }),
        { status: 200 }
      );
    pages[1]!.resolve(page("second"));
    await secondLoading;
    pages[0]!.resolve(page("first"));
    await firstLoading;

    expect(
      useChatSessionStore.getState().sessions.get(SESSION)?.branchPublishedFiles
        ?.files
    ).toEqual(files("second"));
  });

  test("does not recreate a chat that left the store meanwhile", async () => {
    const save = deferred();
    const loading = loadSelectedBranch(SESSION, save.promise, true);
    useChatSessionStore.setState({ sessions: new Map() });
    save.resolve(new Response(null, { status: 500 }));
    await loading;
    expect(useChatSessionStore.getState().sessions.has(SESSION)).toBe(false);
  });
});
