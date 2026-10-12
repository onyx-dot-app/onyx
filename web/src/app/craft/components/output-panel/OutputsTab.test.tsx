import { useLayoutEffect } from "react";
import {
  act,
  deferred,
  render,
  screen,
  setupUser,
} from "@tests/setup/test-utils";
import OutputsTab from "@/app/craft/components/output-panel/OutputsTab";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { FetchError } from "@/lib/fetcher";
import { readOutputThumbnailCache } from "@/app/craft/services/outputThumbnailCache";
import { useUser } from "@/providers/UserProvider";
import type { OutputCard } from "@/app/craft/types/streamingTypes";
import {
  readOutputInventorySnapshot,
  saveOutputInventorySnapshot,
} from "@/app/craft/services/outputInventorySnapshots";

jest.mock("@/providers/UserProvider", () => ({
  useUser: jest.fn(() => ({ user: { id: "cache-user" } })),
}));

jest.mock("motion/react", () => ({ useInView: () => false }));

const refresh = jest.fn(async () => {});
const file = { path: "outputs/reports/summary.md", revision: "1", size: 10 };
const store = () => useBuildSessionStore.getState();
const outputCard: OutputCard = {
  id: "summary",
  kind: "file",
  path: file.path,
  name: "summary.md",
  turn_index: 0,
  revision: 1,
  size_bytes: file.size,
  deleted: false,
  viewed_revision: null,
};

// Persisted turn scope and viewed revisions.
test("includes unavailable overflow outputs only in their turn's collection", () => {
  const available = Array.from({ length: 3 }, (_, index) => ({
    ...outputCard,
    id: `file-${index}`,
    name: `file-${index}.md`,
    path: `outputs/file-${index}.md`,
  }));
  const removed = {
    ...outputCard,
    id: "removed",
    name: "removed.pdf",
    path: "outputs/removed.pdf",
    deleted: true,
  };
  store().updateSessionData("session", {
    outputInventory: Object.fromEntries(
      available.map((card) => [
        card.path,
        { path: card.path, size: 10, revision: "1" },
      ])
    ),
    outputInventoryStatus: "complete",
  });
  const props = {
    sessionId: "session",
    isActive: false,
    onFileOpen: jest.fn(),
    outputCards: [...available, removed],
  };
  const { rerender } = render(<OutputsTab {...props} turnIndex={0} />);
  for (const card of available)
    expect(screen.getByRole("button", { name: card.path })).toBeInTheDocument();
  expect(screen.getByRole("group", { name: removed.path })).toHaveAttribute(
    "aria-disabled",
    "true"
  );
  expect(screen.getByText("No longer available")).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: removed.path })
  ).not.toBeInTheDocument();
  rerender(<OutputsTab {...props} turnIndex={null} />);
  expect(
    screen.queryByRole("group", { name: removed.path })
  ).not.toBeInTheDocument();
});

test.each([null, 0])(
  "opens recreated files despite a stale deleted card in scope %s",
  async (turnIndex) => {
    const restored = {
      ...file,
      path: "outputs/summary.md",
      revision: "restored",
    };
    store().updateSessionData("session", {
      outputInventory: { [restored.path]: restored },
      outputInventoryStatus: "complete",
    });
    const onFileOpen = jest.fn();
    render(
      <OutputsTab
        sessionId="session"
        isActive={false}
        turnIndex={turnIndex}
        outputCards={[{ ...outputCard, path: restored.path, deleted: true }]}
        onFileOpen={onFileOpen}
      />
    );
    await setupUser().click(
      screen.getByRole("button", { name: restored.path })
    );
    expect(onFileOpen).toHaveBeenCalledWith(restored.path, "summary.md");
    expect(screen.queryByText("No longer available")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("img", { name: "New or updated" })
    ).not.toBeInTheDocument();
  }
);

test("shows persisted output cards before the sandbox inventory loads", () => {
  render(
    <OutputsTab
      sessionId="session"
      isActive={false}
      outputCards={[outputCard]}
      turnIndex={0}
      onFileOpen={jest.fn()}
    />
  );
  expect(screen.getByRole("button", { name: file.path })).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "New or updated" })
  ).toBeInTheDocument();
  expect(refresh).not.toHaveBeenCalled();
});

test("scopes files and apps to a turn and switches back to all turns", async () => {
  const otherFile = { path: "outputs/other.md", size: 12, revision: "2" };
  const app: OutputCard = {
    ...outputCard,
    id: "app",
    kind: "app",
    name: "Todo app",
    path: ".",
  };
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file, [otherFile.path]: otherFile },
    outputInventoryStatus: "complete",
  });
  const onAppOpen = jest.fn();
  const onTurnChange = jest.fn();
  const outputCards = [
    outputCard,
    app,
    {
      ...outputCard,
      id: "other",
      path: otherFile.path,
      name: "other.md",
      turn_index: 1,
    },
  ];
  const props = {
    sessionId: "session",
    isActive: false,
    outputCards,
    onFileOpen: jest.fn(),
    onAppOpen,
    onTurnChange,
  };
  const { rerender } = render(<OutputsTab {...props} turnIndex={0} />);
  expect(screen.getByRole("button", { name: file.path })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: otherFile.path })
  ).not.toBeInTheDocument();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Preview your app" }));
  expect(onAppOpen).toHaveBeenCalledWith(app);
  expect(
    screen.queryByRole("button", { name: "Show outputs" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "All outputs" }));
  expect(onTurnChange).toHaveBeenCalledWith(null);
  rerender(<OutputsTab {...props} turnIndex={null} />);
  expect(
    screen.getByRole("button", { name: otherFile.path })
  ).toBeInTheDocument();
});

test("removes the unseen marker only when the displayed revision is acknowledged", () => {
  const props = {
    sessionId: "session",
    isActive: false,
    turnIndex: 0,
    onFileOpen: jest.fn(),
  };
  const { rerender } = render(
    <OutputsTab
      {...props}
      outputCards={[{ ...outputCard, revision: 2, viewed_revision: 1 }]}
    />
  );
  expect(
    screen.getByRole("img", { name: "New or updated" })
  ).toBeInTheDocument();
  rerender(
    <OutputsTab
      {...props}
      outputCards={[{ ...outputCard, revision: 2, viewed_revision: 2 }]}
    />
  );
  expect(
    screen.queryByRole("img", { name: "New or updated" })
  ).not.toBeInTheDocument();
});

beforeEach(() => {
  jest.clearAllMocks();
  sessionStorage.clear();
  useBuildSessionStore.setState({
    sessions: new Map(),
    refreshOutputInventory: refresh,
  });
  store().createSession("session");
});

// Output cards and retained content.
test("browses folders in a pre-provisioned workspace before a session store entry exists", async () => {
  saveOutputInventorySnapshot("cache-user", "welcome-workspace", {
    [file.path]: file,
  });
  const onFileOpen = jest.fn();
  render(
    <OutputsTab
      sessionId="welcome-workspace"
      isActive={false}
      onFileOpen={onFileOpen}
    />
  );
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "reports" }));
  await user.click(screen.getByRole("button", { name: file.path }));
  expect(onFileOpen).toHaveBeenCalledWith(file.path, "summary.md");
});

test("resolves the snapshot owner outside the isolated thumbnail cache", () => {
  saveOutputInventorySnapshot("cache-user", "session", { [file.path]: file });
  render(
    <OutputsTab sessionId="session" isActive={false} onFileOpen={jest.fn()} />
  );
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  expect(useUser).toHaveBeenCalledTimes(1);
});

test("opens a nested output from its card", async () => {
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file },
    outputInventoryStatus: "complete",
  });
  const onFileOpen = jest.fn();
  render(<OutputsTab sessionId="session" isActive onFileOpen={onFileOpen} />);
  expect(screen.getByText("reports")).toBeInTheDocument();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "reports" }));
  await user.click(screen.getByRole("button", { name: file.path }));
  expect(onFileOpen).toHaveBeenCalledWith(file.path, "summary.md");
});

test("retains cached cards through sandbox discovery and refresh failure", () => {
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file },
    outputInventoryStatus: "error",
  });
  render(
    <OutputsTab sessionId="session" isActive={false} onFileOpen={jest.fn()} />
  );
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Could not refresh outputs"
  );
  expect(refresh).not.toHaveBeenCalled();
});

// Activation and filesystem invalidation.
test("reuses the session inventory across tab activation and refreshes only on invalidation", () => {
  const props = { sessionId: "session", onFileOpen: jest.fn() };
  const { rerender } = render(<OutputsTab {...props} isActive={false} />);
  expect(refresh).not.toHaveBeenCalled();
  rerender(<OutputsTab {...props} isActive />);
  expect(refresh).not.toHaveBeenCalled();
  act(() =>
    store().updateSessionData("session", {
      outputInventory: { [file.path]: file },
      filesNeedsRefresh: 1,
      outputInventoryStatus: "complete",
    })
  );
  expect(refresh).not.toHaveBeenCalled();
  rerender(<OutputsTab {...props} isActive={false} />);
  rerender(<OutputsTab {...props} isActive />);
  expect(refresh).not.toHaveBeenCalled();
  act(() => store().triggerFilesRefresh("session"));
  expect(refresh).toHaveBeenCalledTimes(1);
});

test("shows an empty state only after a successful empty inventory", () => {
  store().updateSessionData("session", {
    outputInventory: {},
    outputInventoryStatus: "complete",
  });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Files your agent creates will appear here"
  );
});

test("reports an incomplete scan instead of an empty successful inventory", () => {
  store().updateSessionData("session", {
    outputInventory: {},
    outputInventoryStatus: "partial",
  });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  expect(screen.getByRole("status")).toHaveTextContent(
    "Some outputs could not be loaded"
  );
  expect(
    screen.queryByText("Files your agent creates will appear here.")
  ).not.toBeInTheDocument();
});

test("opens an output card with the keyboard", async () => {
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file },
    outputInventoryStatus: "complete",
  });
  const onFileOpen = jest.fn();
  render(
    <OutputsTab
      sessionId="session"
      isActive
      searchQuery="summary"
      onFileOpen={onFileOpen}
    />
  );
  const user = setupUser();
  await user.tab();
  await user.tab();
  await user.tab();
  expect(screen.getByRole("button", { name: file.path })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(onFileOpen).toHaveBeenCalledWith(file.path, "summary.md");
});

test("leaves active task discovery to streaming when an inventory already exists", () => {
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file },
    activeTurnId: "turn",
    status: "running",
  });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  act(() => store().triggerFilesRefresh("session"));
  expect(refresh).not.toHaveBeenCalled();
});

// Folder scope, search, and file types.
test("searches descendants and returns to folder cards when search clears", () => {
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file },
    outputInventoryStatus: "complete",
  });
  const props = { sessionId: "session", isActive: true, onFileOpen: jest.fn() };
  const { rerender } = render(<OutputsTab {...props} searchQuery="summary" />);
  expect(screen.getByRole("button", { name: file.path })).toBeInTheDocument();
  rerender(<OutputsTab {...props} searchQuery="" />);
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: file.path })
  ).not.toBeInTheDocument();
});

test("filters by type without losing folder navigation", async () => {
  const image = { ...file, path: "outputs/reports/chart.png" };
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file, [image.path]: image },
    outputInventoryStatus: "complete",
  });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "reports" }));
  await user.click(screen.getByRole("button", { name: "File type" }));
  await user.click(screen.getByRole("option", { name: ".png" }));
  expect(screen.getByRole("button", { name: image.path })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: file.path })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Outputs" }));
  expect(screen.getByRole("button", { name: image.path })).toBeInTheDocument();
});

test("offers folders and only extensions present in outputs", async () => {
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file },
    outputInventoryStatus: "complete",
  });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "File type" }));
  expect(
    screen.queryByRole("option", { name: ".png" })
  ).not.toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: "Folders" }));
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: file.path })
  ).not.toBeInTheDocument();
});

// Reload snapshots remain display hints, not discovery state.
test("shows persisted cards immediately, then accepts live replacement without changing discovery baseline", () => {
  saveOutputInventorySnapshot("cache-user", "session", { [file.path]: file });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  expect(store().sessions.get("session")?.outputInventory).toBeNull();
  expect(store().sessions.get("session")?.outputBaselinePending).toBe(true);
  expect(refresh).not.toHaveBeenCalled();
  const replacement = { path: "outputs/new.txt", revision: "2", size: 4 };
  act(() =>
    store().updateSessionData("session", {
      outputInventory: { [replacement.path]: replacement },
      outputInventoryStatus: "complete",
    })
  );
  expect(
    screen.queryByRole("button", { name: "reports" })
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: replacement.path })
  ).toBeInTheDocument();
  expect(readOutputInventorySnapshot("cache-user", "session")).toEqual({
    [replacement.path]: replacement,
  });
});

test("retains reload hints on transient failure and clears them permanently after access denial", () => {
  saveOutputInventorySnapshot("cache-user", "session", { [file.path]: file });
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  act(() =>
    store().updateSessionData("session", {
      outputInventoryStatus: "error",
      outputInventoryError: new FetchError("Offline", 503, null),
    })
  );
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  act(() =>
    store().updateSessionData("session", {
      outputInventoryStatus: "error",
      outputInventoryError: new FetchError("Denied", 403, null),
    })
  );
  expect(
    screen.queryByRole("button", { name: "reports" })
  ).not.toBeInTheDocument();
  expect(readOutputInventorySnapshot("cache-user", "session")).toBeUndefined();
  act(() =>
    store().updateSessionData("session", {
      outputInventoryError: new FetchError("Offline", 503, null),
    })
  );
  expect(
    screen.queryByRole("button", { name: "reports" })
  ).not.toBeInTheDocument();
});

test("does not resurrect persisted cards after an authoritative empty list", () => {
  saveOutputInventorySnapshot("cache-user", "session", { [file.path]: file });
  const { unmount } = render(
    <OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />
  );
  act(() =>
    store().updateSessionData("session", {
      outputInventory: {},
      outputInventoryStatus: "complete",
    })
  );
  expect(
    screen.queryByRole("button", { name: "reports" })
  ).not.toBeInTheDocument();
  unmount();
  expect(readOutputInventorySnapshot("cache-user", "session")).toEqual({});
  render(<OutputsTab sessionId="session" isActive onFileOpen={jest.fn()} />);
  expect(
    screen.queryByRole("button", { name: "reports" })
  ).not.toBeInTheDocument();
});

// Committed inventory fences precede delayed preview writes.
test.each(["complete", "error"] as const)(
  "restores the %s inventory revision fence before a revisited session receives old bytes",
  (status) => {
    const key = "craft-output-thumbnail:session:outputs/image.png";
    store().updateSessionData("session", {
      outputInventory: {
        "outputs/image.png": {
          path: "outputs/image.png",
          revision: "new",
          size: 10,
        },
      },
      outputInventoryStatus: status,
    });
    store().createSession("other");
    let acceptedObsoleteBytes = false;
    function DelayedPreviewCommit() {
      useLayoutEffect(() => {
        readOutputThumbnailCache("cache-user")?.set(key, {
          data: {
            identity: JSON.stringify([key, "old", 0]),
            data: {
              content: "obsolete image",
              mimeType: "image/png",
              isImage: true,
            },
          },
        });
        acceptedObsoleteBytes = Boolean(
          readOutputThumbnailCache("cache-user")?.get(key)?.data?.data
        );
      });
      return null;
    }
    const { rerender } = render(
      <OutputsTab sessionId="session" isActive={false} onFileOpen={jest.fn()} />
    );
    rerender(
      <OutputsTab sessionId="other" isActive={false} onFileOpen={jest.fn()} />
    );
    rerender(
      <>
        <OutputsTab
          sessionId="session"
          isActive={false}
          onFileOpen={jest.fn()}
        />
        <DelayedPreviewCommit />
      </>
    );
    expect(acceptedObsoleteBytes).toBe(false);
    expect(
      readOutputThumbnailCache("cache-user")?.get(key)?.data?.data
    ).toBeUndefined();
  }
);

// --- Unread descendants ---
test("scopes folder unread markers to the selected turn", () => {
  const other = { ...file, path: "outputs/reports/other.md" };
  store().updateSessionData("session", {
    outputInventory: { [file.path]: file, [other.path]: other },
    outputInventoryStatus: "complete",
  });
  store().updateOutputsTabState("session", { fileType: "folders" });
  const props = {
    sessionId: "session",
    isActive: false,
    onFileOpen: jest.fn(),
    outputCards: [
      { ...outputCard, viewed_revision: 1 },
      { ...outputCard, id: "other", path: other.path, turn_index: 1 },
    ],
  };
  const { rerender } = render(<OutputsTab {...props} turnIndex={0} />);
  expect(screen.getByRole("button", { name: "reports" })).toBeInTheDocument();
  expect(
    screen.queryByRole("img", { name: "New or updated" })
  ).not.toBeInTheDocument();
  rerender(<OutputsTab {...props} turnIndex={1} />);
  expect(
    screen.getByRole("img", { name: "New or updated" })
  ).toBeInTheDocument();
});

test("marks each ancestor folder unread until its descendant revision is viewed", async () => {
  const nested = {
    path: "outputs/reports/nested/report.md",
    size: 12,
    revision: "2",
  };
  store().updateSessionData("session", {
    outputInventory: { [nested.path]: nested },
    outputInventoryStatus: "complete",
  });
  const card = {
    ...outputCard,
    path: nested.path,
    revision: 2,
    viewed_revision: 1,
  };
  const props = {
    sessionId: "session",
    isActive: false,
    onFileOpen: jest.fn(),
  };
  const { rerender } = render(<OutputsTab {...props} outputCards={[card]} />);
  expect(
    screen.getByRole("img", { name: "New or updated" })
  ).toBeInTheDocument();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "reports" }));
  expect(screen.getByRole("button", { name: "nested" })).toBeInTheDocument();
  expect(
    screen.getByRole("img", { name: "New or updated" })
  ).toBeInTheDocument();
  rerender(
    <OutputsTab {...props} outputCards={[{ ...card, viewed_revision: 2 }]} />
  );
  expect(
    screen.queryByRole("img", { name: "New or updated" })
  ).not.toBeInTheDocument();
});

test("marks all viewed with a pending state and disables when no unread revisions remain", async () => {
  const pending = deferred<void>();
  const onMarkAllViewed = jest.fn(() => pending.promise);
  const props = {
    sessionId: "session",
    isActive: false,
    onFileOpen: jest.fn(),
    onMarkAllViewed,
  };
  const { rerender } = render(
    <OutputsTab {...props} outputCards={[outputCard]} />
  );
  const button = screen.getByRole("button", { name: "Mark all viewed" });
  await setupUser().click(button);
  expect(onMarkAllViewed).toHaveBeenCalledTimes(1);
  expect(button).toBeDisabled();
  expect(button).toHaveAttribute("aria-busy", "true");
  await act(async () => pending.resolve());
  rerender(
    <OutputsTab
      {...props}
      outputCards={[{ ...outputCard, viewed_revision: outputCard.revision }]}
    />
  );
  expect(button).toBeDisabled();
});

// Session navigation replaces the provider during the same React commit.
test("keeps preview subscriptions alive when switching between cached sessions", () => {
  const first = { path: "outputs/first.png", revision: "1", size: 10 };
  const second = { path: "outputs/second.png", revision: "1", size: 10 };
  store().updateSessionData("session", {
    outputInventory: { [first.path]: first },
    outputInventoryStatus: "complete",
  });
  store().createSession("other", {
    outputInventory: { [second.path]: second },
    outputInventoryStatus: "complete",
  });
  const props = { isActive: false, onFileOpen: jest.fn() };
  const { rerender } = render(
    <OutputsTab key="session" sessionId="session" {...props} />
  );
  expect(screen.getByRole("button", { name: first.path })).toBeInTheDocument();
  rerender(<OutputsTab key="other" sessionId="other" {...props} />);
  act(() =>
    store().updateSessionData("other", {
      outputInventory: { [second.path]: { ...second, revision: "2" } },
    })
  );
  expect(screen.getByRole("button", { name: second.path })).toBeInTheDocument();
  rerender(<OutputsTab key="session" sessionId="session" {...props} />);
  act(() =>
    store().updateSessionData("session", {
      outputInventory: { [first.path]: { ...first, revision: "2" } },
    })
  );
  expect(screen.getByRole("button", { name: first.path })).toBeInTheDocument();
});
