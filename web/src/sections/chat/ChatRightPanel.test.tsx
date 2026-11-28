import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { IncognitoProvider, useIncognito } from "@/providers/IncognitoProvider";
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
  openBrowserInChat,
  useChatSessionStore,
  useRightPanelShown,
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
  useEffect,
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
import type { AppSettings } from "@/lib/settings/types";

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
// The "+" menu offers the browser, and My Chrome while a test turns it on
let mockChromeAvailable = false;
jest.mock("@/lib/settings/hooks", () => {
  const actual = jest.requireActual<typeof import("@/lib/settings/hooks")>(
    "@/lib/settings/hooks"
  );
  return {
    ...actual,
    useSettings: (): AppSettings => ({
      ...actual.useSettings(),
      chat_browser_available: true,
      chrome_browser_available: mockChromeAvailable,
    }),
  };
});
// Marks the globe that browser tabs show
jest.mock("@opal/icons", () => ({
  ...jest.requireActual("@opal/icons"),
  SvgGlobe: () => <svg data-testid="globe-icon" />,
}));
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
  chat_id: null,
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
  incognito = false,
}: {
  replies: PublishedFile[][];
  workspaceWidth?: number;
  retrieval?: boolean;
  incognito?: boolean;
}) {
  const sourcesOpen = useSourcesShown();
  const panelOpen = useRightPanelShown();
  const workspace = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const [panelToggleSlot, setPanelToggleSlot] = useState<HTMLElement | null>(
    null
  );
  const elements = useMemo(
    () => ({ workspace, page, panelToggleSlot, activitySlot: null }),
    [panelToggleSlot]
  );
  return (
    <IncognitoProvider>
      {incognito && <IncognitoOn />}
      <AppWorkspaceElementsContext.Provider value={elements}>
        <div ref={workspace} data-workspace-width={workspaceWidth}>
          <div ref={setPanelToggleSlot} />
          <PublishedFilesPanelContext.Provider
            value={{ ...CHAT_FILES_PANEL, chatId: "session" }}
          >
            <div ref={page} data-testid="page">
              {replies.map((files, index) => (
                <PublishedFileCards key={index} files={files} />
              ))}
            </div>
            <CurrentChatRightPanel
              open={panelOpen && (retrieval || !sourcesOpen)}
              sources={SOURCES}
              hasSources
            />
          </PublishedFilesPanelContext.Provider>
        </div>
      </AppWorkspaceElementsContext.Provider>
    </IncognitoProvider>
  );
}

function IncognitoOn() {
  const { setIncognitoEnabled } = useIncognito();
  useEffect(() => setIncognitoEnabled(true), [setIncognitoEnabled]);
  return null;
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
      .applyLoadedSession("session", load, startChatLoad(undefined), {})
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
    "original",
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
    "original",
    expect.any(AbortSignal)
  );
  expect(panel().fileTabs).toHaveLength(1);
  expect(screen.getByRole("tab", { name: "Final report" })).toBeVisible();
  expect(screen.queryByRole("tab", { name: /v\d of/ })).toBeNull();
});

test("a file tab takes the name that a reload lists after a rename, also on an older version", async () => {
  const first = { ...reportVersion(1), title: null };
  const second = { ...reportVersion(2), title: null };
  renderChat([[first], [second]]);
  applyLoad([second], [[first], [second]]);
  update({ type: "openFile", file: second, pinned: false });
  expect(screen.getByRole("tab", { name: "report.md" })).toBeVisible();

  await act(async () => {
    applyLoad([{ ...second, name: "summary.md" }], [[first], [second]]);
  });
  expect(screen.getByRole("tab", { name: "summary.md" })).toBeVisible();
  expect(
    screen.getByRole("region", { name: "Preview of summary.md" })
  ).toBeInTheDocument();

  update({ type: "openFile", file: first, pinned: true });
  expect(
    screen.getByRole("tab", { name: "summary.md (v1 of 2)" })
  ).toBeVisible();
  expect(screen.queryByRole("tab", { name: /report\.md/ })).toBeNull();
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
    "original",
    expect.any(AbortSignal)
  );

  // A reload lists a version that a background subagent published
  await act(async () => {
    applyLoad([reportVersion(2)], [[first]]);
  });
  expect(fetchChatFile).toHaveBeenLastCalledWith(
    "file-v2",
    "original",
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
    "original",
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
    "original",
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
  update({ type: "showFiles" });
  update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
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
  const mouse = (type: string, target: EventTarget, clientX: number) => {
    act(() => {
      target.dispatchEvent(
        new MouseEvent(type, { bubbles: true, button: 0, clientX })
      );
    });
  };
  // After a drag, dnd-kit stops document clicks for 50ms. The fake clock ends
  // that here, not in the next test.
  jest.useFakeTimers();
  try {
    mouse("mousedown", screen.getByRole("tab", { name: "Q3 report" }), 0);
    mouse("mousemove", document, -20);
    mouse("mouseup", document, -20);
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
  update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
  act(() => screen.getByRole("tab", { name: "Q3 report" }).click());

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
    "original",
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
  const filesOpen = useRightPanelShown();
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
    () => ({ workspace, page, panelToggleSlot, activitySlot: null }),
    [panelToggleSlot]
  );
  onRender?.();
  return (
    <IncognitoProvider>
      <RootLayoutRightPanelSlotContext.Provider value={setSlot}>
        <AppWorkspaceElementsContext.Provider value={elements}>
          <div ref={workspace} data-workspace-width={1000}>
            <div ref={setPanelToggleSlot} />
            <div ref={page}>{children}</div>
            <div data-testid="slot">{slot}</div>
          </div>
        </AppWorkspaceElementsContext.Provider>
      </RootLayoutRightPanelSlotContext.Provider>
    </IncognitoProvider>
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
    chat_id: null,
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
    "original",
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
    "original",
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

test("a file tab's URL bar shows its path and the preview's actions", async () => {
  renderChat([[REPORT]]);
  await act(async () => {
    screen.getByRole("button", { name: "Preview report.md" }).click();
  });
  const shown = await preview("Q3 report");
  expect(screen.getByTestId("url-bar-pill")).toHaveTextContent("report.md");
  // The actions sit in the URL bar's row, not over the preview
  const bar = screen.getByTestId("url-bar-pill").parentElement!;
  expect(
    await within(bar).findByRole("link", { name: "Download" })
  ).toBeVisible();
  expect(
    within(bar).getByRole("button", { name: "Copy content" })
  ).toBeVisible();
  expect(
    within(bar).getByRole("button", { name: "Show source" })
  ).toBeVisible();
  expect(within(shown).queryByRole("link", { name: "Download" })).toBeNull();
});

// The chat browser's websocket, which a test drives by hand
class FakeSocket extends EventTarget {
  static instances: FakeSocket[] = [];
  readyState = 0;
  binaryType = "blob";
  sent: unknown[] = [];
  constructor(readonly url: string) {
    super();
    FakeSocket.instances.push(this);
  }
  send(data: string) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  open() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }
  receive(message: object) {
    this.dispatchEvent(
      Object.assign(new Event("message"), { data: JSON.stringify(message) })
    );
  }
}

const PAGE = {
  id: "t1",
  url: "https://example.com/",
  title: "Example Domain",
  loading: false,
  dialog: null,
};
// A page without a title shows its host
const DOCS_PAGE = {
  ...PAGE,
  id: "t2",
  url: "https://docs.example.org/guide",
  title: "",
};

describe("the chat's browser", () => {
  const originalWebSocket = globalThis.WebSocket;
  const socket = () => {
    const last = FakeSocket.instances.at(-1);
    if (!last) throw new Error("The panel opened no websocket");
    return last;
  };
  const receive = (message: object) => act(() => socket().receive(message));
  // A tab's icon sits beside its label, in the tab's frame
  const globeOf = (tab: HTMLElement) =>
    tab
      .closest<HTMLElement>('[role="presentation"]')
      ?.querySelector('[data-testid="globe-icon"]');

  beforeEach(() => {
    FakeSocket.instances = [];
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: FakeSocket,
    });
    jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
  });
  afterEach(() => {
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: originalWebSocket,
    });
  });

  test("the agent's browser_open shows the browser, whose pages are tabs with a globe beside Files", () => {
    renderChat([[REPORT]]);
    update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
    update({ type: "showFiles" });
    update({ type: "closePanel" });
    // Another chat's packet does not open this chat's panel
    act(() => openBrowserInChat("another-session"));
    expect(panel().mode).toBe("closed");

    act(() => openBrowserInChat("session"));
    // Until the stream lists the pages, the browser has one tab
    const browserTab = screen.getByRole("tab", { name: "Browser" });
    expect(browserTab).toHaveAttribute("aria-selected", "true");
    expect(globeOf(browserTab)).toBeInTheDocument();
    expect(screen.getByText("Connecting to the browser")).toBeVisible();
    expect(socket().url).toBe(
      "ws://localhost/api/chat/sessions/session/browser/ws"
    );

    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE, DOCS_PAGE], selected: "t1" });
    const strip = screen.getByRole("tablist");
    expect(
      within(strip)
        .getAllByRole("tab")
        .map((tab) => tab.getAttribute("aria-label") ?? tab.textContent)
    ).toEqual(["Files", "Sources", "Example Domain", "docs.example.org"]);
    const example = screen.getByRole("tab", { name: "Example Domain" });
    expect(example).toHaveAttribute("aria-selected", "true");
    for (const name of ["Example Domain", "docs.example.org"])
      expect(globeOf(screen.getByRole("tab", { name }))).toBeInTheDocument();
    expect(panel().activeId).toBe("browser");
    // No second row of tabs inside the browser
    expect(screen.queryByRole("toolbar")).not.toBeInTheDocument();
    expect(socket().sent).toEqual([]);

    // Files hides the browser and keeps its tabs and connection
    act(() => screen.getByRole("tab", { name: "Files" }).click());
    expect(
      screen.getByRole("tab", { name: "docs.example.org" })
    ).toBeInTheDocument();
    expect(FakeSocket.instances).toHaveLength(1);
  });

  test("a browser tab selects its page, and the stream's selection marks the active tab", () => {
    renderChat([[REPORT]]);
    update({ type: "showFiles" });
    act(() => openBrowserInChat("session"));
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE, DOCS_PAGE], selected: "t1" });

    act(() => screen.getByRole("tab", { name: "docs.example.org" }).click());
    expect(socket().sent).toEqual([{ type: "selectTab", tab: "t2" }]);
    receive({ type: "tabs", tabs: [PAGE, DOCS_PAGE], selected: "t2" });
    expect(
      screen.getByRole("tab", { name: "docs.example.org" })
    ).toHaveAttribute("aria-selected", "true");
    expect(socket().sent).toHaveLength(1);
    expect(FakeSocket.instances).toHaveLength(1);

    // From Files, a page's tab shows the browser on that page
    act(() => screen.getByRole("tab", { name: "Files" }).click());
    act(() => screen.getByRole("tab", { name: "Example Domain" }).click());
    expect(socket().sent.at(-1)).toEqual({ type: "selectTab", tab: "t1" });
    expect(panel().activeId).toBe("browser");
    receive({ type: "tabs", tabs: [PAGE, DOCS_PAGE], selected: "t1" });
    expect(screen.getByRole("tab", { name: "Example Domain" })).toHaveAttribute(
      "aria-selected",
      "true"
    );

    // The page closes in the browser; its tab goes with the page list
    receive({ type: "tabs", tabs: [PAGE, DOCS_PAGE], selected: "t2" });
    act(() =>
      screen.getByRole("button", { name: "Close docs.example.org" }).click()
    );
    expect(socket().sent.at(-1)).toEqual({ type: "closeTab", tab: "t2" });
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    expect(
      screen.queryByRole("tab", { name: "docs.example.org" })
    ).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Example Domain" })).toHaveAttribute(
      "aria-selected",
      "true"
    );

    // The service moves the selection to a page that the agent opens
    receive({
      type: "tabs",
      tabs: [PAGE, { ...PAGE, id: "t3", title: "Agent page" }],
      selected: "t3",
    });
    expect(screen.getByRole("tab", { name: "Agent page" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(socket().sent.at(-1)).toEqual({ type: "closeTab", tab: "t2" });

    // The last page closed: the browser closes and the panel goes back to
    // Files
    receive({ type: "tabs", tabs: [], selected: null });
    expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(panel().browserOpen).toBe(false);
    expect(socket().readyState).toBe(3);
  });

  test("Files and Sources stay beside the browser in a chat without files, and close with their close buttons", () => {
    renderChat([]);
    update({ type: "showTab", tabId: RIGHT_PANEL_SOURCES_TAB });
    update({ type: "showFiles" });
    act(() => openBrowserInChat("session"));
    const strip = screen.getByRole("tablist");
    const tabNames = () =>
      within(strip)
        .getAllByRole("tab")
        .map((tab) => tab.getAttribute("aria-label") ?? tab.textContent);
    expect(tabNames()).toEqual(["Files", "Sources", "Browser"]);

    // Opening Files again shows its one tab
    update({ type: "showFiles" });
    expect(tabNames()).toEqual(["Files", "Sources", "Browser"]);
    expect(screen.getByRole("tab", { name: "Files" })).toHaveAttribute(
      "aria-selected",
      "true"
    );

    act(() => screen.getByRole("button", { name: "Close Files" }).click());
    expect(tabNames()).toEqual(["Sources", "Browser"]);
    act(() => screen.getByRole("button", { name: "Close Sources" }).click());
    expect(tabNames()).toEqual(["Browser"]);
    expect(panel().mode).not.toBe("closed");
  });

  test("an incognito chat's + menu offers no browser", async () => {
    setReplies([[REPORT]]);
    render(<Chat replies={[[REPORT]]} incognito />);
    update({ type: "showTab", tabId: "files" });
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    expect(
      (await screen.findAllByRole("menuitem")).map((item) => item.textContent)
    ).toEqual(["Files", "Sources"]);
  });

  test("Browser in the + menu opens a new page and shows it", async () => {
    renderChat([[REPORT]]);
    update({ type: "showTab", tabId: "files" });
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    // The + menu opens any panel tab: Files, the browser, and Sources when
    // the chat has sources
    expect(
      (await screen.findAllByRole("menuitem")).map((item) => item.textContent)
    ).toEqual(["Files", "Browser", "Sources"]);
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));
    // The new page opens once the browser connects
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    expect(socket().sent).toEqual([{ type: "newTab" }]);
    const blank = { ...PAGE, id: "t2", url: "about:blank", title: "" };
    receive({ type: "tabs", tabs: [PAGE, blank], selected: "t2" });
    // A new page has neither title nor host
    const tabs = within(screen.getByRole("tablist")).getAllByRole("tab");
    expect(tabs.at(-1)).toHaveAccessibleName("Browser");
    expect(tabs.at(-1)).toHaveAttribute("aria-selected", "true");
    expect(panel().activeId).toBe("browser");
    expect(screen.getByText("No page yet")).toBeVisible();

    // On a live browser it opens another page at once
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));
    expect(socket().sent.at(-1)).toEqual({ type: "newTab" });
    expect(FakeSocket.instances).toHaveLength(1);
  });

  test("each Browser asked for before the connection opens its own page", async () => {
    renderChat([[REPORT]]);
    update({ type: "showTab", tabId: "files" });
    for (let i = 0; i < 2; i++) {
      fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
      fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));
    }
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    expect(socket().sent).toEqual([{ type: "newTab" }, { type: "newTab" }]);
  });

  test("a new page asked for before the connection goes only to its own chat's browser", async () => {
    renderChat([[REPORT]]);
    update({ type: "showTab", tabId: "files" });
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));
    // Closing the browser before it connects drops the new page
    act(() => screen.getByRole("button", { name: "Close Browser" }).click());
    expect(panel().browserOpen).toBe(false);
    act(() => openBrowserInChat("session"));
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    expect(socket().sent).toEqual([]);
  });

  test("an edited URL does not follow the user to another chat's page of the same id", () => {
    // Both chats have their browser open
    const store = useChatSessionStore.getState();
    store.createSession("other");
    useChatSessionStore.setState({ currentSessionId: "other" });
    store.updateCurrentRightPanel({ type: "openBrowser" });
    useChatSessionStore.setState({ currentSessionId: "session" });
    renderChat([[REPORT]]);
    act(() => openBrowserInChat("session"));
    const live = () => {
      socket().open();
      socket().receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
      socket().receive({ type: "control", controller: "you" });
    };
    act(live);
    const address = () => screen.getByRole("textbox", { name: "Address" });
    fireEvent.change(address(), { target: { value: "typed.example" } });
    expect(address()).toHaveValue("typed.example");
    act(() => useChatSessionStore.setState({ currentSessionId: "other" }));
    // The other chat's VM names its first page t1 too
    act(live);
    expect(address()).toHaveValue("https://example.com/");
  });

  test("a download's toast downloads the file from the chat's browser", () => {
    const toastInfo = jest.spyOn(toast, "info");
    const clicked: HTMLAnchorElement[] = [];
    jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this);
      });
    renderChat([[REPORT]]);
    act(() => openBrowserInChat("session"));
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    receive({ type: "download", fileName: "a b.csv" });
    expect(toastInfo).toHaveBeenCalledTimes(1);
    const [message, options] = toastInfo.mock.calls[0]!;
    expect(message).toBe("The browser downloaded a b.csv");
    expect(options?.action?.label).toBe("Download");
    act(() => options?.action?.onClick());
    expect(clicked).toHaveLength(1);
    expect(clicked[0]!.getAttribute("href")).toBe(
      "/api/chat/sessions/session/browser/downloads/a%20b.csv"
    );
    expect(clicked[0]!.download).toBe("a b.csv");
  });

  test("a browser error shows a translated toast with the service's detail", () => {
    const toastError = jest.spyOn(toast, "error");
    renderChat([[REPORT]]);
    act(() => openBrowserInChat("session"));
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    receive({ type: "error", message: "net::ERR_NAME_NOT_RESOLVED" });
    expect(toastError).toHaveBeenCalledWith(
      "The browser could not do that. Try again.",
      { description: "net::ERR_NAME_NOT_RESOLVED" }
    );
  });

  test("a download's toast shows and saves its name without bidi controls", () => {
    const toastInfo = jest.spyOn(toast, "info");
    const clicked: HTMLAnchorElement[] = [];
    jest
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        clicked.push(this);
      });
    renderChat([[REPORT]]);
    act(() => openBrowserInChat("session"));
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    receive({ type: "download", fileName: "invoice\u202Efdp.exe" });
    const [message, options] = toastInfo.mock.calls[0]!;
    expect(message).toBe("The browser downloaded invoicefdp.exe");
    act(() => options?.action?.onClick());
    expect(clicked[0]!.download).toBe("invoicefdp.exe");
    // The service stores the file under the name that it sent
    expect(clicked[0]!.getAttribute("href")).toBe(
      "/api/chat/sessions/session/browser/downloads/invoice%E2%80%AEfdp.exe"
    );
  });

  test("a new page asked for before the connection does not go to another chat's browser", async () => {
    renderChat([[REPORT]]);
    update({ type: "showTab", tabId: "files" });
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "Browser" }));
    act(() => {
      useChatSessionStore.getState().createSession("other");
      useChatSessionStore.setState({ currentSessionId: "other" });
    });
    update({ type: "openBrowser" });
    act(() => socket().open());
    expect(socket().url).toContain("/sessions/other/");
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    expect(socket().sent).toEqual([]);
  });

  test("a page's close button closes the browser when the connection is down", () => {
    jest.useFakeTimers();
    try {
      renderChat([[REPORT]]);
      act(() => openBrowserInChat("session"));
      act(() => socket().open());
      receive({ type: "tabs", tabs: [PAGE, DOCS_PAGE], selected: "t1" });
      act(() => {
        socket().readyState = 3;
        socket().dispatchEvent(
          Object.assign(new Event("close"), { code: 1006 })
        );
      });
      act(() =>
        screen.getByRole("button", { name: "Close docs.example.org" }).click()
      );
      expect(panel().browserOpen).toBe(false);
      expect(
        screen.queryByRole("tab", { name: "Example Domain" })
      ).not.toBeInTheDocument();
    } finally {
      jest.useRealTimers();
    }
  });

  test("the focus on the tab that stands for the browser goes to the page's tab", () => {
    renderChat([[REPORT]]);
    act(() => openBrowserInChat("session"));
    const browserTab = screen.getByRole("tab", { name: "Browser" });
    act(() => browserTab.focus());
    act(() => socket().open());
    receive({ type: "tabs", tabs: [PAGE], selected: "t1" });
    expect(screen.getByRole("tab", { name: "Example Domain" })).toHaveFocus();
  });
});

/** A JSON response; the jsdom fetch polyfill has no `Response.json`. */
function jsonResponse(body: object): Response {
  return new Response(JSON.stringify(body), {
    headers: { "Content-Type": "application/json" },
  });
}

/** Shows a reply that waits for approval of each of `tools`. */
function showApprovals(tools: string[]) {
  const user: Message = {
    nodeId: 1,
    messageId: 1,
    type: "user",
    message: "Look it up",
    files: [],
    packets: [],
    toolCall: null,
    parentNodeId: null,
    latestChildNodeId: 2,
    childrenNodeIds: [2],
  };
  const reply: Message = {
    nodeId: 2,
    messageId: 2,
    type: "assistant",
    message: "",
    files: [],
    packets: tools.map((tool) => ({
      placement: { turn_index: 1, tab_index: 0 },
      obj: {
        type: PacketType.TOOL_APPROVAL_REQUEST,
        approval_id: tool,
        tool_call_id: `call-${tool}`,
        tool_name: tool,
        display_name: tool,
        arguments: {},
        agent_name: null,
      },
    })),
    toolCall: null,
    parentNodeId: 1,
    latestChildNodeId: null,
    childrenNodeIds: [],
  };
  useChatSessionStore.getState().updateSessionMessageTree(
    "session",
    new Map([
      [1, user],
      [2, reply],
    ])
  );
}

describe("the user's Chrome", () => {
  const originalWebSocket = globalThis.WebSocket;
  // The chat's Chrome state that the panel fetches
  let grant: { expires_at: number } | null = null;
  // The DELETE calls that stop the chat's use of Chrome
  let stopCalls = 0;

  beforeEach(() => {
    mockChromeAvailable = true;
    grant = null;
    FakeSocket.instances = [];
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: FakeSocket,
    });
    jest.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
    stopCalls = 0;
    jest.spyOn(globalThis, "fetch").mockImplementation(async (_input, init) => {
      if (init?.method === "DELETE") {
        stopCalls += 1;
        grant = null;
      }
      return jsonResponse({
        installations: [{ installation_id: "i1" }],
        grant:
          grant === null
            ? null
            : {
                tabs: [
                  {
                    id: "1",
                    title: "Wiki",
                    url: "https://wiki.example/",
                    origin: "https://wiki.example",
                    controller: "agent",
                  },
                ],
                current: "1",
                origins: ["https://wiki.example"],
                side_panel: false,
                ...grant,
              },
      });
    });
  });
  afterEach(() => {
    mockChromeAvailable = false;
    Object.defineProperty(globalThis, "WebSocket", {
      configurable: true,
      writable: true,
      value: originalWebSocket,
    });
  });

  const openChrome = async () => {
    update({ type: "showTab", tabId: "files" });
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: "My Chrome" }));
  };

  test("while the chat shares tabs, the agent's browser opens My Chrome, and the + menu offers no sandbox browser", async () => {
    grant = { expires_at: Date.now() / 1000 + 600 };
    renderChat([[REPORT]]);
    await openChrome();
    expect(await screen.findByText("Using your Chrome")).toBeVisible();

    act(() => openBrowserInChat("session"));
    await waitFor(() => expect(panel().browserOpen).toBe(false));
    expect(panel().activeId).toBe("chrome");
    expect(FakeSocket.instances).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Open a tab" }));
    expect(
      (await screen.findAllByRole("menuitem")).map((item) => item.textContent)
    ).toEqual(["Files", "My Chrome", "Sources"]);
  });

  test("a share that expired since the last fetch leaves the agent's browser in the sandbox", async () => {
    grant = { expires_at: Date.now() / 1000 + 600 };
    renderChat([[REPORT]]);
    await openChrome();
    await screen.findByText("Using your Chrome");

    // The share ends before the next fetch
    const later = Date.now() + 601_000;
    jest.spyOn(Date, "now").mockReturnValue(later);
    act(() => openBrowserInChat("session"));
    expect(screen.getByRole("tab", { name: "Browser" })).toHaveAttribute(
      "aria-selected",
      "true"
    );
    expect(panel().browserOpen).toBe(true);
  });

  test("a turn that binds Chrome before the panel's next fetch opens My Chrome", async () => {
    renderChat([[REPORT]]);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    // The turn binds the chat to Chrome as it starts; the panel's last
    // fetch still says there is no grant
    grant = { expires_at: Date.now() / 1000 + 600 };
    act(() => openBrowserInChat("session"));
    await waitFor(() => expect(panel().browserOpen).toBe(false));
    expect(panel().activeId).toBe("chrome");
  });

  test("a sandbox browser that was open before the share stays open", async () => {
    renderChat([[REPORT]]);
    act(() => openBrowserInChat("session"));
    expect(panel().browserOpen).toBe(true);
    // The user shares tabs while the sandbox turn still runs
    grant = { expires_at: Date.now() / 1000 + 600 };
    await openChrome();
    // The open tab polls; its next fetch sees the share
    await screen.findByText("Using your Chrome", {}, { timeout: 5000 });
    expect(panel().browserOpen).toBe(true);
    expect(screen.getByRole("tab", { name: "Browser" })).toBeInTheDocument();

    // The next send starts a turn that uses Chrome
    act(() =>
      useChatSessionStore.getState().updateChatState("session", "loading")
    );
    await waitFor(() => expect(panel().browserOpen).toBe(false));
    expect(panel().activeId).toBe("chrome");
  });

  test("My Chrome opened first does not mark the chat's files as seen", async () => {
    renderChat([[REPORT]]);
    update({ type: "openChrome" });
    await screen.findByText("Your Chrome is ready");
    expect(panel().seenInitialized).toBe(false);
  });

  test("Stop ends the chat's use of Chrome", async () => {
    grant = { expires_at: Date.now() / 1000 + 600 };
    renderChat([[REPORT]]);
    await openChrome();
    await screen.findByText("Using your Chrome");

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(stopCalls).toBe(1));
    expect(await screen.findByText("Your Chrome is ready")).toBeVisible();
  });

  test("a pending site approval shows over the idle state, and a tool that is not a browser tool does not", async () => {
    renderChat([[REPORT]]);
    act(() => showApprovals(["browser_navigate", "web_search"]));
    await openChrome();
    await screen.findByText("Your Chrome is ready");

    const overlay = await screen.findByTestId("chrome-site-approvals");
    expect(
      within(overlay).getByRole("button", {
        name: "Approval requested: browser_navigate",
      })
    ).toBeVisible();
    expect(
      within(overlay).queryByRole("button", {
        name: "Approval requested: web_search",
      })
    ).toBeNull();
  });

  test("My Chrome closes when the workspace turns it off", async () => {
    const view = renderChat([[REPORT]]);
    await openChrome();
    await screen.findByText("Your Chrome is ready");

    mockChromeAvailable = false;
    view.rerender(<Chat replies={[[REPORT]]} />);
    await waitFor(() => expect(panel().chromeOpen).toBe(false));
    expect(
      screen.queryByRole("tab", { name: "My Chrome" })
    ).not.toBeInTheDocument();
  });
});
