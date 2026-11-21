import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { fileResponse } from "@tests/setup/fileResponse";
import {
  PacketType,
  type PublishedFile,
} from "@/app/app/services/streamingModels";
import {
  type BackendChatSession,
  ChatSessionSharedStatus,
  type Message,
} from "@/app/app/types";
import {
  useChatSessionStore,
  useFilesShown,
  useSourcesShown,
} from "@/app/app/stores/useChatSessionStore";
import {
  RIGHT_PANEL_SOURCES_TAB,
  type ChatRightPanelAction,
} from "@/lib/chat/rightPanel";
import { AppWorkspaceElementsContext } from "@/layouts/chromes/AppWorkspace";
import {
  type ComponentProps,
  type ReactNode,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  RootLayout,
  RootLayoutRightPanelSlotContext,
  toast,
} from "@opal/layouts";
import { ChatSidePanel } from "@/sections/chat/ChatSidePanel";
import {
  CHAT_FILES_PANEL,
  CurrentChatRightPanel,
  openPublishedFileInChat,
} from "@/sections/chat/ChatRightPanel";
import {
  PublishedFileCards,
  PublishedFilesPanelContext,
} from "@/sections/chat/PublishedFileCards";
import { fetchChatFile } from "@/lib/chat/svc";
import { startChatLoad } from "@/lib/chat/publishedFiles";

// Counts the panel's renders: the frame renders whenever the panel does
const mockPanelRenders = jest.fn();
jest.mock("@/sections/chat/ChatSidePanel", () => {
  const actual = jest.requireActual<
    typeof import("@/sections/chat/ChatSidePanel")
  >("@/sections/chat/ChatSidePanel");
  return {
    ChatSidePanel: (props: ComponentProps<typeof ChatSidePanel>) => {
      mockPanelRenders();
      return actual.ChatSidePanel(props);
    },
  };
});
jest.mock("@/lib/chat/svc", () => ({
  ...jest.requireActual("@/lib/chat/svc"),
  fetchChatFile: jest.fn(),
}));

const REPORT: PublishedFile = {
  file_id: "file-1",
  name: "report.md",
  title: "Q3 report",
  path: "/home/onyx/report.md",
  display_path: "report.md",
  size: 10,
  mime_type: "text/markdown",
  artifact_id: "artifact-report",
  version: 1,
  thumbnail_file_id: null,
};
const CHART: PublishedFile = {
  ...REPORT,
  file_id: "file-2",
  name: "chart.md",
  title: "Chart",
  path: "/home/onyx/chart.md",
  display_path: "chart.md",
  artifact_id: "artifact-chart",
};
/** Version `version` of the report, saved as file `file-v<version>`. */
const reportVersion = (version: number, title = REPORT.title) => ({
  ...REPORT,
  file_id: `file-v${version}`,
  title,
  version,
});

function markdownResponse(): Response {
  const headers: Record<string, string> = {
    "Content-Type": "text/markdown",
    "Content-Disposition": 'attachment; filename="report.md"',
  };
  const response: Pick<Response, "headers" | "blob" | "body"> = {
    headers: { get: (name: string) => headers[name] ?? null } as Headers,
    blob: async () =>
      ({
        text: async () => "Revenue grew.",
        type: "text/markdown",
      }) as unknown as Blob,
    body: null,
  };
  return response as unknown as Response;
}

/**
 * The replies' cards and the chat page's right panel, wired to the store, in
 * an app chrome workspace of `workspaceWidth`, or one not measured yet.
 * Without `retrieval`, the page hides a panel that shows Sources.
 */
function Chat({
  replies,
  workspaceWidth = 0,
  retrieval = true,
}: {
  replies: PublishedFile[][];
  workspaceWidth?: number;
  retrieval?: boolean;
}) {
  const sourcesOpen = useSourcesShown();
  const filesOpen = useFilesShown();
  const workspace = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const [panelToggleSlot, setPanelToggleSlot] = useState<HTMLElement | null>(
    null
  );
  const elements = useMemo(
    () => ({ workspace, page, panelToggleSlot }),
    [panelToggleSlot]
  );
  return (
    <AppWorkspaceElementsContext.Provider value={elements}>
      <div ref={workspace} data-workspace-width={workspaceWidth}>
        <div ref={setPanelToggleSlot} />
        <PublishedFilesPanelContext.Provider value={CHAT_FILES_PANEL}>
          <div ref={page} data-testid="page">
            {replies.map((files, index) => (
              <PublishedFileCards key={index} files={files} />
            ))}
          </div>
          <CurrentChatRightPanel
            open={(retrieval && sourcesOpen) || filesOpen}
            sources={SOURCES}
            hasSources
          />
        </PublishedFilesPanelContext.Provider>
      </div>
    </AppWorkspaceElementsContext.Provider>
  );
}

const SOURCES = <p>Cited documents</p>;

function renderChat(replies: PublishedFile[][]) {
  setReplies(replies);
  return render(<Chat replies={replies} />);
}

function update(action: ChatRightPanelAction) {
  act(() => useChatSessionStore.getState().updateCurrentRightPanel(action));
}

/** Saves replies that published `replies`, one answer each. */
function setReplies(replies: PublishedFile[][]) {
  const messages = replies.map(
    (files, index): Message => ({
      nodeId: index + 1,
      messageId: index + 1,
      type: "assistant",
      message: "",
      files: [],
      packets: [
        {
          placement: { turn_index: 0, tab_index: 0 },
          obj: { type: PacketType.PUBLISH_FILES_END, files, error: null },
        },
      ],
      toolCall: null,
      parentNodeId: null,
    })
  );
  useChatSessionStore
    .getState()
    .updateSessionMessageTree(
      "session",
      new Map(messages.map((message) => [message.nodeId, message]))
    );
}

/** Applies a load whose list is `listed` and whose packets publish `replies`. */
function applyLoad(listed: PublishedFile[], replies: PublishedFile[][]) {
  const load: BackendChatSession = {
    chat_session_id: "session",
    description: "Chat",
    persona_id: 0,
    persona_name: "Assistant",
    messages: [],
    time_created: new Date().toISOString(),
    time_updated: new Date().toISOString(),
    shared_status: ChatSessionSharedStatus.Private,
    current_temperature_override: null,
    current_reasoning_effort_override: null,
    owner_name: null,
    packets: replies.map((files) => [
      {
        placement: { turn_index: 0, tab_index: 0 },
        obj: { type: PacketType.PUBLISH_FILES_END, files, error: null },
      },
    ]),
    published_files: listed,
  };
  act(() =>
    useChatSessionStore
      .getState()
      .applyLoadedSession("session", load, startChatLoad(), {})
  );
}

function panel() {
  return useChatSessionStore.getState().sessions.get("session")!.rightPanel;
}

beforeAll(() => {
  Object.defineProperty(window.URL, "createObjectURL", {
    configurable: true,
    value: () => "blob:report",
  });
  Object.defineProperty(window.URL, "revokeObjectURL", {
    configurable: true,
    value: () => undefined,
  });
});

beforeEach(() => {
  sessionStorage.clear();
  useChatSessionStore.setState({
    sessions: new Map(),
    currentSessionId: "session",
  });
  useChatSessionStore.getState().createSession("session");
  jest.mocked(fetchChatFile).mockResolvedValue(markdownResponse());
  // The workspace's measured width
  jest
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      const width = Number(this.dataset.workspaceWidth ?? 0);
      return DOMRect.fromRect({ x: 0, y: 0, width, height: 0 });
    });
});

afterEach(() => {
  jest.restoreAllMocks();
});

const preview = (title: string) =>
  screen.findByRole("region", { name: `Preview of ${title}` });

test("a reply's card opens its file in its own tab, in place of Sources", async () => {
  renderChat([[REPORT]]);
  update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
  expect(screen.getByText("Cited documents")).toBeVisible();

  const card = screen.getByRole("button", { name: "Preview report.md" });
  await act(async () => {
    card.focus();
    card.click();
  });

  const region = await preview("Q3 report");
  // Focus lands on the preview, and the panel does not take it back
  expect(region).toHaveFocus();
  expect(screen.getByRole("tab", { name: "Q3 report" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.queryByText("Cited documents")).toBeNull();
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a reply shows five cards, and its view-all button shows the Files list", async () => {
  const files = Array.from({ length: 7 }, (_, index) => ({
    ...REPORT,
    file_id: `file-${index}`,
    name: `report-${index}.md`,
    title: `Report ${index}`,
    path: `/home/onyx/report-${index}.md`,
    display_path: `report-${index}.md`,
    artifact_id: `artifact-${index}`,
  }));
  renderChat([files]);
  expect(screen.getAllByRole("button", { name: /^Preview / })).toHaveLength(5);
  expect(screen.queryByText("Report 5")).toBeNull();

  await act(async () => {
    screen.getByRole("button", { name: "View all 7 files" }).click();
  });
  expect(screen.getByRole("button", { name: "Open Report 6" })).toBeVisible();
});

test("Escape after a card in a new chat goes back to the Files list, not to Sources", async () => {
  renderChat([[REPORT]]);
  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  fireEvent.keyDown(await preview("Q3 report"), { key: "Escape" });

  expect(screen.queryByText("Cited documents")).toBeNull();
  expect(screen.getByRole("button", { name: "Open Q3 report" })).toHaveFocus();
});

test("an older version's card opens that version in the artifact's tab, which says so", async () => {
  const older = reportVersion(1, "Draft report");
  const newer = reportVersion(2, "Final report");
  renderChat([[older], [newer]]);
  const cards = screen.getAllByRole("button", { name: "Preview report.md" });

  await act(async () => {
    cards[0]!.click();
  });
  expect(await preview("Draft report")).toBeVisible();
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v1",
    false,
    expect.any(AbortSignal)
  );
  // The name shows apart from the sentence, so a U+202E or right-to-left
  // name cannot reorder the version
  const tab = screen.getByRole("tab", { name: "Draft report (v1 of 2)" });
  expect(tab.querySelector("bdi")).toHaveTextContent(/^Draft report$/);
  expect(tab).toHaveTextContent(/^Draft report \(v1 of 2\)$/);

  // The newest version's card takes the same tab, without a label
  await act(async () => {
    cards[1]!.click();
  });
  expect(await preview("Final report")).toBeVisible();
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v2",
    false,
    expect.any(AbortSignal)
  );
  expect(panel().fileTabs).toHaveLength(1);
  expect(screen.getByRole("tab", { name: "Final report" })).toBeVisible();
  expect(screen.queryByRole("tab", { name: /v\d of/ })).toBeNull();
});

test("an open tab follows the newest version after a reload and a live publish; a pinned tab keeps its version", async () => {
  const first = reportVersion(1);
  renderChat([[first]]);
  applyLoad([first], [[first]]);
  update({ type: "showFiles" });
  await act(async () => {
    screen.getByRole("button", { name: "Open Q3 report" }).click();
  });
  await preview("Q3 report");
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v1",
    false,
    expect.any(AbortSignal)
  );

  // A reload lists a version that a background subagent published
  await act(async () => {
    applyLoad([reportVersion(2)], [[first]]);
  });
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v2",
    false,
    expect.any(AbortSignal)
  );
  expect(
    document.querySelector('[data-published-preview="file-v2"]')
  ).not.toBeNull();

  // A live answer publishes another version
  await act(async () => {
    setReplies([[first], [reportVersion(3)]]);
  });
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v3",
    false,
    expect.any(AbortSignal)
  );
  expect(screen.getByRole("tab", { name: "Q3 report" })).toBeVisible();

  // The first card pins the tab to its version, through later publishes
  act(() => openPublishedFileInChat(first));
  expect(
    screen.getByRole("tab", { name: "Q3 report (v1 of 3)" })
  ).toBeVisible();
  await act(async () => {
    setReplies([[first], [reportVersion(3)], [reportVersion(4)]]);
  });
  expect(
    screen.getByRole("tab", { name: "Q3 report (v1 of 4)" })
  ).toBeVisible();
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v1",
    false,
    expect.any(AbortSignal)
  );
});

test("a tab that moves to a new version starts a fresh preview and stops the old download", async () => {
  const photo = (version: number): PublishedFile => ({
    ...reportVersion(version),
    name: "photo.png",
    path: "/home/onyx/photo.png",
    display_path: "photo.png",
    mime_type: "image/png",
  });
  // The first version's download never ends
  jest
    .mocked(fetchChatFile)
    .mockImplementation((fileId) =>
      fileId === "file-v1"
        ? new Promise(() => undefined)
        : Promise.resolve(fileResponse("png", "image/png", "photo.png"))
    );
  renderChat([[photo(1)]]);
  await act(async () => {
    screen.getByRole("button", { name: "Preview photo.png" }).click();
  });
  await preview("Q3 report");
  const firstDownload = jest
    .mocked(fetchChatFile)
    .mock.calls.find(([fileId]) => fileId === "file-v1")?.[2];
  expect(firstDownload?.aborted).toBe(false);

  await act(async () => {
    setReplies([[photo(1)], [photo(2)]]);
  });
  await waitFor(() => expect(firstDownload?.aborted).toBe(true));
  fireEvent.error(
    await within(await preview("Q3 report")).findByRole("img", {
      name: "photo.png",
    })
  );
  expect(await screen.findByText("Cannot preview this file")).toBeVisible();

  await act(async () => {
    setReplies([[photo(1)], [photo(2)], [photo(3)]]);
  });
  expect(
    await within(await preview("Q3 report")).findByRole("img", {
      name: "photo.png",
    })
  ).toBeVisible();
  expect(screen.queryByText("Cannot preview this file")).toBeNull();
});

test("several files open, switch and close like Craft's tabs", async () => {
  renderChat([[REPORT, CHART]]);
  update({ type: "showFiles" });
  await act(async () => {
    screen.getByRole("button", { name: "Open Q3 report" }).click();
  });
  act(() => screen.getByRole("tab", { name: "Files" }).click());
  await act(async () => {
    screen.getByRole("button", { name: "Open Chart" }).click();
  });
  expect(await preview("Chart")).toBeVisible();

  // Switching back keeps the first file's viewer: it does not load again,
  // and a tab switch leaves focus on the tab strip.
  const loads = jest.mocked(fetchChatFile).mock.calls.length;
  const reportTab = screen.getByRole("tab", { name: "Q3 report" });
  reportTab.focus();
  await act(async () => {
    reportTab.click();
  });
  expect(await preview("Q3 report")).toBeVisible();
  expect(jest.mocked(fetchChatFile).mock.calls).toHaveLength(loads);
  expect(reportTab).toHaveFocus();

  await act(async () => {
    screen.getByRole("button", { name: "Close Q3 report" }).click();
  });
  expect(screen.queryByRole("tab", { name: "Q3 report" })).toBeNull();
  expect(screen.getByRole("tab", { name: "Chart" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
});

test("only file tabs move, and the strip announces only real moves", async () => {
  renderChat([[REPORT, CHART]]);
  act(() => openPublishedFileInChat(REPORT));
  act(() => openPublishedFileInChat(CHART));
  const fileTabs = () => panel().fileTabs;
  const order = fileTabs();
  const moved = () => screen.queryByText(/^Tab moved to position/);

  // A file tab cannot move before the fixed tabs, and they cannot move
  fireEvent.keyDown(screen.getByRole("tab", { name: "Q3 report" }), {
    key: "ArrowLeft",
    altKey: true,
  });
  fireEvent.keyDown(screen.getByRole("tab", { name: "Sources" }), {
    key: "ArrowRight",
    altKey: true,
  });
  expect(fileTabs()).toEqual(order);
  expect(moved()).toBeNull();

  // A drag cannot drop a file tab on a fixed tab. Every tab measures zero
  // here, so the drop lands on the first droppable tab.
  const pointer = (type: string, target: EventTarget, clientX: number) => {
    // jsdom has no PointerEvent; dnd-kit reads these mouse event fields
    const event = new MouseEvent(type, { bubbles: true, button: 0, clientX });
    Object.defineProperty(event, "isPrimary", { value: true });
    act(() => {
      target.dispatchEvent(event);
    });
  };
  // After a drag, dnd-kit stops document clicks for 50ms. The fake clock ends
  // that here, not in the next test.
  jest.useFakeTimers();
  try {
    pointer("pointerdown", screen.getByRole("tab", { name: "Q3 report" }), 0);
    pointer("pointermove", document, -20);
    pointer("pointerup", document, -20);
    act(() => jest.advanceTimersByTime(50));
  } finally {
    jest.useRealTimers();
  }
  expect(fileTabs()).toEqual(order);
  expect(moved()).toBeNull();

  fireEvent.keyDown(screen.getByRole("tab", { name: "Q3 report" }), {
    key: "ArrowRight",
    altKey: true,
  });
  expect(fileTabs()).toEqual([...order].reverse());
  expect(moved()).toHaveTextContent("Tab moved to position 4 of 4");
});

test("tabs switch between Files, Sources and a file, and the Sources control opens Sources", async () => {
  renderChat([[REPORT]]);
  act(() => openPublishedFileInChat(REPORT));
  expect(await preview("Q3 report")).toBeVisible();

  act(() => screen.getByRole("tab", { name: "Sources" }).click());
  expect(screen.getByText("Cited documents")).toBeVisible();
  act(() => screen.getByRole("tab", { name: "Files" }).click());
  expect(screen.queryByText("Cited documents")).toBeNull();
  expect(screen.getByRole("button", { name: "Open Q3 report" })).toBeVisible();

  // A citation's Sources control opens the panel on Sources.
  update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
  expect(screen.getByText("Cited documents")).toBeVisible();
});

test("a full panel makes the page inert and takes focus out of it, until Escape restores it", () => {
  setReplies([[REPORT]]);
  render(<Chat replies={[[REPORT]]} workspaceWidth={1200} />);
  update({ type: "showFiles" });
  const card = screen.getByRole("button", { name: "Preview report.md" });
  card.focus();

  update({ type: "setMode", mode: "full" });
  expect(screen.getByTestId("page").inert).toBe(true);
  expect(screen.getByRole("button", { name: "Toggle panel" })).toHaveFocus();

  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(panel().mode).toBe("medium");
  expect(screen.getByTestId("page").inert).toBe(false);
});

test("the panel sits over the workspace's end beside the page's reserve, and fills the workspace at full size", () => {
  setReplies([[REPORT]]);
  render(<Chat replies={[[REPORT]]} workspaceWidth={1200} />);
  update({ type: "showFiles" });
  const box = screen.getByRole("complementary", {
    name: "Files",
  }).parentElement!;
  const reserve = box.parentElement!;
  const geometry = () => ({
    over: box.classList.contains("absolute") && box.classList.contains("end-0"),
    width: box.style.width,
    reserve: reserve.style.width,
  });
  const medium = { over: true, width: "600px", reserve: "600px" };
  expect(geometry()).toEqual(medium);

  update({ type: "setMode", mode: "full" });
  expect(geometry()).toEqual({ ...medium, width: "100%" });

  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(geometry()).toEqual(medium);
});

test("closing a panel that covers a narrow chat returns focus to the card that opened it", async () => {
  setReplies([[REPORT]]);
  render(<Chat replies={[[REPORT]]} workspaceWidth={600} />);
  // Opened before, the panel knows the width when it opens: it covers the
  // page in the same render
  update({ type: "showFiles" });
  update({ type: "closePanel" });
  const card = screen.getByRole("button", { name: "Preview report.md" });
  await act(async () => {
    card.focus();
    card.click();
  });
  await preview("Q3 report");
  expect(screen.getByTestId("page").inert).toBe(true);

  update({ type: "closePanel" });
  expect(screen.getByTestId("page").inert).toBe(false);
  expect(card).toHaveFocus();
});

test("on a narrow workspace, which hides the size button, Escape first closes the open file", async () => {
  setReplies([[REPORT]]);
  render(<Chat replies={[[REPORT]]} workspaceWidth={600} />);
  act(() => openPublishedFileInChat(REPORT));
  update({ type: "setMode", mode: "full" });
  const region = await preview("Q3 report");
  expect(screen.queryByRole("button", { name: "Expand panel" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Restore panel" })).toBeNull();
  expect(screen.getByTestId("page").inert).toBe(true);

  fireEvent.keyDown(region, { key: "Escape" });
  expect(screen.queryByRole("tab", { name: "Q3 report" })).toBeNull();
});

test("files of one shown name show their paths", async () => {
  const draft = {
    ...REPORT,
    file_id: "file-draft",
    path: "/home/onyx/drafts/report.md",
    display_path: "drafts/report.md",
    artifact_id: "artifact-draft",
  };
  const older = reportVersion(1, "Q2 report");
  const newest = reportVersion(2);
  renderChat([[older], [draft, newest]]);
  // Files lists the newest version of each artifact, by path where the
  // shown names match
  update({ type: "showFiles" });
  expect(
    screen.getByRole("button", { name: "Open drafts/report.md" })
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Open report.md" })).toBeVisible();
  expect(screen.queryByRole("button", { name: "Open Q2 report" })).toBeNull();

  act(() => openPublishedFileInChat(draft));
  act(() => openPublishedFileInChat(newest));

  // Names that the sandbox chose show in their own direction
  expect(screen.getByRole("tab", { name: "drafts/report.md" })).toHaveAttribute(
    "dir",
    "auto"
  );
  expect(screen.getByRole("tab", { name: "report.md" })).toBeInTheDocument();
  await preview("Q3 report");
});

test("Escape from an older version's preview focuses its artifact's tile", async () => {
  const older = reportVersion(1, "Q2 report");
  renderChat([[older], [reportVersion(2)]]);
  act(() => openPublishedFileInChat(older));
  fireEvent.keyDown(await preview("Q2 report"), { key: "Escape" });

  expect(screen.getByRole("button", { name: "Open Q3 report" })).toHaveFocus();
});

test("Escape from a preview without a tile focuses the Files tab, and the next Escape closes the panel", async () => {
  // The server's list leaves out a file whose object is missing
  const pathless = { ...REPORT, file_id: "file-pathless", title: "Pathless" };
  renderChat([[pathless]]);
  applyLoad([], [[pathless]]);
  act(() => openPublishedFileInChat(pathless));
  fireEvent.keyDown(await preview("Pathless"), { key: "Escape" });

  const filesTab = screen.getByRole("tab", { name: "Files" });
  expect(filesTab).toHaveFocus();
  fireEvent.keyDown(filesTab, { key: "Escape" });
  expect(panel().mode).toBe("closed");
});

test("a card opened after a tab moves takes focus to its preview", async () => {
  renderChat([[REPORT, CHART]]);
  act(() => openPublishedFileInChat(REPORT));
  act(() => openPublishedFileInChat(CHART));
  await preview("Chart");
  fireEvent.keyDown(screen.getByRole("tab", { name: "Q3 report" }), {
    key: "ArrowRight",
    altKey: true,
  });

  const card = screen.getByRole("button", { name: "Preview report.md" });
  await act(async () => {
    card.focus();
    card.click();
  });
  expect(await preview("Q3 report")).toHaveFocus();
});

test("a card that opens another version of the shown artifact takes focus to its preview; a new version that the tab follows does not", async () => {
  const older = reportVersion(1, "Draft report");
  const newer = reportVersion(2, "Final report");
  renderChat([[older], [newer]]);
  const cards = screen.getAllByRole("button", { name: "Preview report.md" });
  await act(async () => {
    cards[1]!.focus();
    cards[1]!.click();
  });
  expect(await preview("Final report")).toHaveFocus();

  await act(async () => {
    cards[0]!.focus();
    cards[0]!.click();
  });
  expect(await preview("Draft report")).toHaveFocus();

  await act(async () => {
    cards[1]!.focus();
    cards[1]!.click();
  });
  expect(await preview("Final report")).toHaveFocus();

  cards[0]!.focus();
  await act(async () => {
    setReplies([[older], [newer], [reportVersion(3, "Revised report")]]);
  });
  await preview("Revised report");
  expect(cards[0]).toHaveFocus();
});

test("a tab of a version newer than the listed one shows that version, without a label", async () => {
  // The newest version's object is missing, so the server lists the older
  const older = reportVersion(1);
  const newer = reportVersion(2);
  renderChat([[older], [newer]]);
  applyLoad([older], [[older], [newer]]);

  act(() => openPublishedFileInChat(newer));
  expect(screen.getByRole("tab", { name: "Q3 report" })).toBeInTheDocument();
  expect(screen.queryByRole("tab", { name: /v\d of/ })).toBeNull();
  await preview("Q3 report");
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v2",
    false,
    expect.any(AbortSignal)
  );
});

test("the keyboard and a double click resize the panel and keep the width for the chat", () => {
  setReplies([[REPORT]]);
  render(<Chat replies={[[REPORT]]} workspaceWidth={1000} />);
  update({ type: "showFiles" });
  const handle = screen.getByRole("separator", { name: "Resize panel" });
  expect(handle).toHaveAttribute("aria-valuenow", "500");

  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(panel().proportion).toBeCloseTo(0.52);
  fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
  expect(panel().proportion).toBeCloseTo(0.44);
  fireEvent.doubleClick(handle);
  expect(panel().proportion).toBe(0.5);
});

/** An answer delta, which replaces the message tree and its packets. */
function streamDelta() {
  act(() => {
    const tree = useChatSessionStore
      .getState()
      .sessions.get("session")!.messageTree;
    const message = tree.get(1)!;
    useChatSessionStore.getState().updateSessionMessageTree(
      "session",
      new Map([
        [
          1,
          {
            ...message,
            packets: [
              ...message.packets,
              {
                placement: { turn_index: 1, tab_index: 0 },
                obj: { type: PacketType.MESSAGE_DELTA, content: "Done" },
              },
            ],
          },
        ],
      ])
    );
  });
}

// The page renders on every packet, and places the panel's memoized element
// in the right panel slot, as AppPage does
function StreamingPage() {
  useChatSessionStore(
    (state) => state.sessions.get(state.currentSessionId ?? "")?.messageTree
  );
  const filesOpen = useFilesShown();
  const rightPanel = useMemo(
    () => (
      <CurrentChatRightPanel open={filesOpen} sources={SOURCES} hasSources />
    ),
    [filesOpen]
  );
  return <RootLayout.RightPanel>{rightPanel}</RootLayout.RightPanel>;
}

/**
 * The app chrome: it shows the right panel slot that the page fills, in the
 * workspace that the panel shares with the page.
 */
function Chrome({
  children,
  onRender,
}: {
  children: ReactNode;
  onRender?: () => void;
}) {
  const [slot, setSlot] = useState<ReactNode>(null);
  const workspace = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const [panelToggleSlot, setPanelToggleSlot] = useState<HTMLElement | null>(
    null
  );
  const elements = useMemo(
    () => ({ workspace, page, panelToggleSlot }),
    [panelToggleSlot]
  );
  onRender?.();
  return (
    <RootLayoutRightPanelSlotContext.Provider value={setSlot}>
      <AppWorkspaceElementsContext.Provider value={elements}>
        <div ref={workspace} data-workspace-width={1000}>
          <div ref={setPanelToggleSlot} />
          <div ref={page}>{children}</div>
          <div data-testid="slot">{slot}</div>
        </div>
      </AppWorkspaceElementsContext.Provider>
    </RootLayoutRightPanelSlotContext.Provider>
  );
}

test("a streamed packet that changes no file or tab does not render the panel", async () => {
  setReplies([[REPORT]]);
  render(
    <Chrome>
      <StreamingPage />
    </Chrome>
  );
  act(() => openPublishedFileInChat(REPORT));
  await preview("Q3 report");
  const before = mockPanelRenders.mock.calls.length;

  streamDelta();
  expect(mockPanelRenders.mock.calls).toHaveLength(before);
});

test("streamed packets, the Files search and a resize do not render the app chrome that holds the panel", async () => {
  setReplies([[REPORT]]);
  const chromeRenders = jest.fn();
  render(
    <Chrome onRender={chromeRenders}>
      <StreamingPage />
    </Chrome>
  );
  act(() => openPublishedFileInChat(REPORT));
  await preview("Q3 report");
  expect(
    within(screen.getByTestId("slot")).getByRole("tab", { name: "Q3 report" })
  ).toBeInTheDocument();
  const before = chromeRenders.mock.calls.length;

  for (let delta = 0; delta < 200; delta++) streamDelta();
  act(() => screen.getByRole("tab", { name: "Files" }).click());
  const search = screen.getByRole("searchbox", { name: "Search files" });
  for (const query of ["r", "re", "rep", "repo", "repor", "report"])
    fireEvent.change(search, { target: { value: query } });
  // A drag of the panel's edge, saved on release. jsdom has no pointer
  // events or pointer capture.
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
    }
  }
  const pointerEvent = Object.getOwnPropertyDescriptor(window, "PointerEvent");
  Object.defineProperty(window, "PointerEvent", {
    configurable: true,
    value: TestPointerEvent,
  });
  const handle = screen.getByRole("separator", { name: "Resize panel" });
  Object.assign(handle, {
    setPointerCapture: () => undefined,
    hasPointerCapture: () => false,
  });
  try {
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 450 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 450 });
  } finally {
    if (pointerEvent)
      Object.defineProperty(window, "PointerEvent", pointerEvent);
    else Reflect.deleteProperty(window, "PointerEvent");
  }
  expect(panel().proportion).toBeCloseTo(0.55);
  expect(chromeRenders.mock.calls.length - before).toBe(0);
});

test("a closed panel does not watch the workspace's width, and measures it again on opening", () => {
  const observers: { callback: ResizeObserverCallback; target: Element }[] = [];
  jest.spyOn(window, "ResizeObserver").mockImplementation(
    (callback) =>
      ({
        observe: (target: Element) => observers.push({ callback, target }),
        unobserve: () => undefined,
        disconnect: () => {
          observers.splice(
            0,
            observers.length,
            ...observers.filter((entry) => entry.callback !== callback)
          );
        },
      }) as unknown as ResizeObserver
  );
  setReplies([[REPORT]]);
  const view = render(<Chat replies={[[REPORT]]} workspaceWidth={1000} />);
  update({ type: "showFiles" });
  update({ type: "closePanel" });
  expect(
    observers.filter(
      ({ target }) =>
        target instanceof HTMLElement && target.dataset.workspaceWidth
    )
  ).toHaveLength(0);
  const before = mockPanelRenders.mock.calls.length;

  for (let width = 900; width < 960; width++)
    act(() => {
      for (const { callback, target } of observers)
        if (target instanceof HTMLElement && target.dataset.workspaceWidth)
          callback(
            [
              {
                target,
                contentRect: DOMRect.fromRect({ width }),
              } as unknown as ResizeObserverEntry,
            ],
            {} as ResizeObserver
          );
    });
  expect(mockPanelRenders.mock.calls.length - before).toBe(0);

  // The workspace grew while the panel was closed
  view.container
    .querySelector<HTMLElement>("[data-workspace-width]")!
    .setAttribute("data-workspace-width", "1200");
  update({ type: "showFiles" });
  expect(
    screen.getByRole("separator", { name: "Resize panel" })
  ).toHaveAttribute("aria-valuemax", "800");
});

test("the Files search filters the tiles, and a file published later is marked new", () => {
  const view = renderChat([[REPORT]]);
  update({ type: "showFiles" });
  // A file listed when the panel first opened is not new.
  expect(screen.queryByRole("img", { name: "New or updated" })).toBeNull();

  setReplies([[REPORT], [CHART]]);
  view.rerender(<Chat replies={[[REPORT], [CHART]]} />);
  expect(screen.getAllByRole("img", { name: "New or updated" })).toHaveLength(
    1
  );

  fireEvent.change(screen.getByRole("searchbox", { name: "Search files" }), {
    target: { value: "chart" },
  });
  expect(screen.queryByRole("button", { name: "Open Q3 report" })).toBeNull();
  expect(screen.getByRole("button", { name: "Open Chart" })).toBeVisible();

  // The search matches the path as shown, without bidi controls
  const odd = {
    ...CHART,
    file_id: "file-odd",
    title: "Odd",
    artifact_id: "artifact-odd",
    display_path: "drafts/\u202Eodd.md",
  };
  setReplies([[REPORT], [CHART, odd]]);
  view.rerender(<Chat replies={[[REPORT], [CHART, odd]]} />);
  fireEvent.change(screen.getByRole("searchbox", { name: "Search files" }), {
    target: { value: "drafts/odd" },
  });
  expect(screen.getByRole("button", { name: "Open Odd" })).toBeVisible();
});

test("a card opens its own file, also one that the Files list does not hold", async () => {
  // A file saved without an artifact: the server's list leaves it out, so
  // the Files list does not show it
  const pathless = {
    ...REPORT,
    file_id: "file-pathless",
    title: "Pathless",
    artifact_id: null,
    version: null,
    thumbnail_file_id: null,
  };
  renderChat([[pathless]]);
  applyLoad([], [[pathless]]);
  update({ type: "showFiles" });
  expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  expect(screen.queryByRole("button", { name: "Open Pathless" })).toBeNull();

  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });

  expect(await preview("Pathless")).toBeVisible();
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-pathless",
    false,
    expect.any(AbortSignal)
  );
  expect(screen.getByRole("tab", { name: "Pathless" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
});

test("a card saved without an artifact shares its listed file's tab, and Escape returns to the tile", async () => {
  const card = { ...REPORT, artifact_id: null, version: null };
  renderChat([[card]]);
  applyLoad([REPORT], [[card]]);
  act(() => openPublishedFileInChat(card));
  await preview("Q3 report");
  update({ type: "showTab", tabId: "files" });
  await act(async () => {
    screen.getByRole("button", { name: "Open Q3 report" }).click();
  });

  expect(panel().fileTabs).toEqual([{ file: REPORT, pinned: false }]);
  fireEvent.keyDown(await preview("Q3 report"), { key: "Escape" });
  expect(screen.getByRole("button", { name: "Open Q3 report" })).toHaveFocus();
});

test("an open tab that moves to a new version marks that version seen", async () => {
  const first = reportVersion(1);
  renderChat([[first]]);
  update({ type: "showFiles" });
  await act(async () => {
    screen.getByRole("button", { name: "Open Q3 report" }).click();
  });
  await preview("Q3 report");

  await act(async () => {
    setReplies([[first], [reportVersion(2)]]);
  });
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v2",
    false,
    expect.any(AbortSignal)
  );
  expect(panel().seenFileIds).toContain("file-v2");
  update({ type: "showTab", tabId: "files" });
  expect(screen.queryByRole("img", { name: "New or updated" })).toBeNull();
});

const panelToggle = () => screen.getByRole("button", { name: "Toggle panel" });

test("the panel toggle shows in a chat without files and opens and closes the panel", () => {
  renderChat([]);

  expect(panelToggle()).toHaveAttribute("aria-expanded", "false");
  // Closed, the toggle comes before the page in keyboard order
  expect(
    panelToggle().compareDocumentPosition(screen.getByTestId("page")) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
  act(() => panelToggle().click());
  expect(panel().mode).toBe("medium");
  const filesTab = screen.getByRole("tab", { name: "Files" });
  expect(filesTab).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("This chat has no files yet")).toBeVisible();
  expect(panelToggle()).toHaveAttribute("aria-expanded", "true");
  // Open, it comes before the panel's tabs
  expect(
    panelToggle().compareDocumentPosition(filesTab) &
      Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();

  act(() => panelToggle().click());
  expect(panel().mode).toBe("closed");
  expect(panelToggle()).toHaveAttribute("aria-expanded", "false");
  // Closing gives focus back to the toggle in its new place
  expect(panelToggle()).toHaveFocus();
});

test("closing with the toggle focuses the toggle, not the element that had focus at opening", () => {
  renderChat([[REPORT]]);
  // Focus elsewhere when the toggle opens the panel, as the chat input can be
  screen.getByRole("button", { name: "Preview report.md" }).focus();
  act(() => panelToggle().click());
  act(() => panelToggle().click());
  expect(panel().mode).toBe("closed");
  expect(panelToggle()).toHaveFocus();
});

test("the panel toggle closes the panel also from Sources", () => {
  renderChat([[REPORT]]);
  update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });

  act(() => panelToggle().click());
  expect(panel().mode).toBe("closed");
});

test("the panel toggle opens Files in one click when the page hides Sources", () => {
  setReplies([[REPORT]]);
  render(<Chat replies={[[REPORT]]} retrieval={false} />);
  // The stored state shows Sources, which the page hides without retrieval
  update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
  expect(panelToggle()).toHaveAttribute("aria-expanded", "false");

  act(() => panelToggle().click());
  expect(panelToggle()).toHaveAttribute("aria-expanded", "true");
  expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
});

test("reload in the URL bar loads the file list, keeps the open file, and is off while it runs", async () => {
  renderChat([[REPORT]]);
  applyLoad([REPORT], [[REPORT]]);
  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(await preview("Q3 report")).toBeVisible();
  const fileLoads = jest.mocked(fetchChatFile).mock.calls.length;

  let respond: (response: Response) => void = () => undefined;
  const fetchPage = jest.spyOn(global, "fetch").mockReturnValue(
    new Promise((resolve) => {
      respond = resolve;
    })
  );
  const reload = screen.getByRole("button", { name: "Refresh files" });
  await act(async () => reload.click());
  // As Craft's, it is off while the reload runs
  expect(reload).toBeDisabled();
  expect(reload).toHaveAttribute("aria-busy", "true");
  expect(fetchPage).toHaveBeenCalledTimes(1);
  expect(fetchPage).toHaveBeenCalledWith(
    expect.stringMatching(/^\/api\/chat\/get-chat-session\/session\?limit=/),
    expect.objectContaining({ cache: "no-store" })
  );

  // The server now lists a file that no packet here published
  await act(async () =>
    respond(
      new Response(
        JSON.stringify({ packets: [], published_files: [CHART, REPORT] })
      )
    )
  );
  expect(reload).toBeEnabled();
  // The file's tab keeps its file, not loaded again
  expect(await preview("Q3 report")).toBeVisible();
  expect(jest.mocked(fetchChatFile).mock.calls.length).toBe(fileLoads);
  act(() => screen.getByRole("tab", { name: "Files" }).click());
  expect(screen.getByRole("button", { name: "Open Chart" })).toBeVisible();
});

test("a reload that fails says so and keeps the list", async () => {
  renderChat([[REPORT]]);
  applyLoad([REPORT], [[REPORT]]);
  update({ type: "showFiles" });
  const toastError = jest.spyOn(toast, "error");
  jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response("", { status: 500 }));
  jest.spyOn(console, "error").mockImplementation(() => undefined);

  const reload = screen.getByRole("button", { name: "Refresh files" });
  await act(async () => reload.click());
  expect(toastError).toHaveBeenCalledWith(
    "Could not reload the files. Try again."
  );
  expect(reload).toBeEnabled();
  expect(screen.getByRole("button", { name: "Open Q3 report" })).toBeVisible();
});

test("a file tab's URL bar shows its path and downloads it", async () => {
  renderChat([[REPORT]]);
  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  expect(await preview("Q3 report")).toBeVisible();
  expect(screen.getByTestId("url-bar-pill")).toHaveTextContent("report.md");
  // The preview draws no download of its own: the URL bar has it
  expect(
    within(await preview("Q3 report")).queryByRole("link", {
      name: "Download",
    })
  ).toBeNull();
  const click = jest
    .spyOn(HTMLAnchorElement.prototype, "click")
    .mockImplementation(() => undefined);
  act(() => screen.getByRole("button", { name: "Download file" }).click());
  expect(click).toHaveBeenCalledTimes(1);
});
