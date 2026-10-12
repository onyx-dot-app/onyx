import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { act, render, screen, fireEvent } from "@tests/setup/test-utils";
import CraftWorkspace from "@/app/craft/components/CraftWorkspace";
import {
  readOutputPanelPreferences,
  saveOutputPanelPreferences,
  clearOutputPanelPreferences,
  type OutputPanelPreferences,
} from "@/app/craft/services/outputPanelPreferences";

jest.mock("@/app/craft/components/ChatPanel", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/OutputPanel", () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock("@/app/craft/components/SandboxAsleepNotice", () => ({
  __esModule: true,
  default: () => null,
}));

const preferences: OutputPanelPreferences = {
  outputPanelMode: "full",
  outputPanelInitialized: true,
  panelTabs: [
    {
      kind: "browser",
      id: "browser-1",
      appId: "session-a",
      appName: "Local App",
    },
    { kind: "file", path: "outputs/report.md", fileName: "report.md" },
    { kind: "files" },
    { kind: "outputs" },
  ],
  activePanelTabId: "file:outputs/report.md",
  mediumPanelProportion: 0.6,
  filesTabState: {
    expandedPaths: ["outputs", "outputs/reports"],
    scrollTop: 120,
  },
};

beforeEach(() => {
  sessionStorage.clear();
  useBuildSessionStore.setState({
    sessions: new Map(),
    currentSessionId: null,
    noSessionOutputPanelInitialized: false,
  });
});

test("opens an uncached history session with its preferences instead of welcome tabs", () => {
  saveOutputPanelPreferences("session-a", preferences);
  const store = useBuildSessionStore.getState;
  store().openFilesTab(null);
  const welcomeWorkspace = store().noSessionOutputWorkspaceId;

  store().setCurrentSession("session-a");

  expect(store().sessions.get("session-a")).toMatchObject(preferences);
  expect(store().sessions.get("session-a")?.outputWorkspaceId).not.toBe(
    welcomeWorkspace
  );
});

test("recreates the same panel after the in-memory session is lost", () => {
  saveOutputPanelPreferences("session-a", preferences);
  useBuildSessionStore.getState().setCurrentSession("session-a");
  expect(
    useBuildSessionStore.getState().sessions.get("session-a")
  ).toMatchObject(preferences);
  useBuildSessionStore.setState({
    sessions: new Map(),
    currentSessionId: null,
  });
  useBuildSessionStore.getState().setCurrentSession("session-a");
  expect(
    useBuildSessionStore.getState().sessions.get("session-a")
  ).toMatchObject(preferences);
  useBuildSessionStore.getState().setCurrentSession("session-b");
  expect(
    useBuildSessionStore.getState().sessions.get("session-b")
  ).toMatchObject({
    outputPanelMode: "closed",
    panelTabs: [],
    activePanelTabId: null,
  });
});

test("saves panel controls immediately and restores the workspace after remount", () => {
  useBuildSessionStore.getState().setCurrentSession("session-a");
  const { container, unmount } = render(
    <CraftWorkspace existingSessionId="session-a" />
  );
  act(() => {
    const store = useBuildSessionStore.getState();
    store.openFilesTab("session-a");
    store.openFilePreview("session-a", "outputs/report.md", "report.md");
    store.setCurrentMediumPanelProportion(0.6);
    store.setCurrentOutputPanelMode("full");
  });
  expect(readOutputPanelPreferences("session-a")).toMatchObject({
    outputPanelMode: "full",
    activePanelTabId: "file:outputs/report.md",
    mediumPanelProportion: 0.6,
  });
  expect(container.querySelector("[data-output-mode]")).toHaveAttribute(
    "data-output-mode",
    "full"
  );
  unmount();
  useBuildSessionStore.setState({
    sessions: new Map(),
    currentSessionId: null,
  });
  useBuildSessionStore.getState().setCurrentSession("session-a");
  render(<CraftWorkspace existingSessionId="session-a" />);
  expect(
    screen.getByRole("button", { name: "Restore outputs" })
  ).toBeInTheDocument();
  expect(
    useBuildSessionStore.getState().sessions.get("session-a")?.panelTabs
  ).toEqual([
    { kind: "files" },
    { kind: "file", path: "outputs/report.md", fileName: "report.md" },
  ]);
});

test("restores open geometry before enabling later layout transitions", () => {
  jest.useFakeTimers();
  let measure = () => {};
  const resize = jest
    .spyOn(global, "ResizeObserver")
    .mockImplementation((callback) => {
      const observer: ResizeObserver = {
        observe: (target) => {
          if (
            !(target instanceof HTMLElement) ||
            !target.hasAttribute("data-output-mode")
          )
            return;
          measure = () =>
            callback(
              [
                {
                  target,
                  contentRect: new DOMRect(0, 0, 1200, 720),
                  borderBoxSize: [],
                  contentBoxSize: [],
                  devicePixelContentBoxSize: [],
                },
              ],
              observer
            );
        },
        unobserve: () => {},
        disconnect: () => {},
      };
      return observer;
    });
  try {
    saveOutputPanelPreferences("session-a", preferences);
    useBuildSessionStore.getState().setCurrentSession("session-a");
    const { container } = render(
      <CraftWorkspace existingSessionId="session-a" />
    );
    const root = container.querySelector("[data-output-mode]");
    const chat = root?.firstElementChild;
    expect(root).toHaveAttribute("data-output-mode", "full");
    expect(chat).not.toHaveClass("transition-[width]");
    act(() => measure());
    expect(chat).not.toHaveClass("transition-[width]");
    act(() => jest.advanceTimersByTime(20));
    expect(chat).toHaveClass("transition-[width]");
  } finally {
    resize.mockRestore();
    jest.useRealTimers();
  }
});

test("restores an open empty panel and explicit closed state", () => {
  saveOutputPanelPreferences("empty", {
    ...preferences,
    panelTabs: [],
    activePanelTabId: null,
  });
  useBuildSessionStore.getState().setCurrentSession("empty");
  expect(useBuildSessionStore.getState().sessions.get("empty")).toMatchObject({
    outputPanelMode: "full",
    panelTabs: [],
    activePanelTabId: null,
  });
  saveOutputPanelPreferences("closed", {
    ...preferences,
    outputPanelMode: "closed",
  });
  expect(readOutputPanelPreferences("closed")?.outputPanelMode).toBe("closed");
  clearOutputPanelPreferences("closed");
  expect(readOutputPanelPreferences("closed")).toBeUndefined();
});

test("ignores invalid saved state and repairs a missing selection", () => {
  sessionStorage.setItem(
    "onyx:craft:output-panel:v1:invalid",
    JSON.stringify({
      ...preferences,
      panelTabs: [{ kind: "file", path: 42 }],
    })
  );
  expect(readOutputPanelPreferences("invalid")).toBeUndefined();
  saveOutputPanelPreferences("selection", {
    ...preferences,
    activePanelTabId: "missing",
  });
  expect(readOutputPanelPreferences("selection")?.activePanelTabId).toBe(
    "browser:browser-1"
  );
});

test("keeps controls usable when storage is blocked", () => {
  const blocked = jest
    .spyOn(Storage.prototype, "setItem")
    .mockImplementation(() => {
      throw new Error("Storage blocked");
    });
  expect(() =>
    saveOutputPanelPreferences("session-a", preferences)
  ).not.toThrow();
  blocked.mockRestore();
  sessionStorage.setItem("onyx:craft:output-panel:v1:invalid", "{");
  expect(readOutputPanelPreferences("invalid")).toBeUndefined();
});

test("previews resizing locally and saves only on release", () => {
  jest.useFakeTimers();
  const resize = jest
    .spyOn(global, "ResizeObserver")
    .mockImplementation((callback) => {
      const observer: ResizeObserver = {
        observe: (target) => {
          if (
            !(target instanceof HTMLElement) ||
            !target.hasAttribute("data-output-mode")
          )
            return;
          callback(
            [
              {
                target,
                contentRect: new DOMRect(0, 0, 1200, 720),
                borderBoxSize: [],
                contentBoxSize: [],
                devicePixelContentBoxSize: [],
              },
            ],
            observer
          );
        },
        unobserve: () => {},
        disconnect: () => {},
      };
      return observer;
    });
  try {
    saveOutputPanelPreferences("session-a", {
      ...preferences,
      outputPanelMode: "medium",
      mediumPanelProportion: 0.5,
    });
    useBuildSessionStore.getState().setCurrentSession("session-a");
    const { container } = render(
      <CraftWorkspace existingSessionId="session-a" />
    );
    act(() => jest.advanceTimersByTime(20));
    const root = container.querySelector<HTMLElement>("[data-output-mode]")!;
    jest
      .spyOn(root, "getBoundingClientRect")
      .mockReturnValue(new DOMRect(0, 0, 1200, 720));
    const divider = screen.getByRole("separator");
    divider.setPointerCapture = jest.fn();
    divider.hasPointerCapture = () => true;
    divider.releasePointerCapture = jest.fn();
    const pointer = (type: string, clientX: number, pointerId = 1) => {
      const event = new MouseEvent(type, { bubbles: true, button: 0, clientX });
      Object.defineProperty(event, "pointerId", { value: pointerId });
      fireEvent(divider, event);
    };
    const saved = () =>
      readOutputPanelPreferences("session-a")?.mediumPanelProportion;
    pointer("pointerdown", 600);
    pointer("pointermove", 550);
    pointer("pointermove", 500);
    expect(divider).toHaveAttribute("aria-valuenow", "600");
    expect(saved()).toBe(0.5);
    act(() => jest.advanceTimersByTime(20));
    expect(divider).toHaveAttribute("aria-valuenow", "700");
    expect(saved()).toBe(0.5);
    pointer("pointermove", 450);
    pointer("pointerup", 450);
    expect(saved()).toBe(0.625);
    expect(divider).toHaveAttribute("aria-valuenow", "750");
    expect(divider.style.insetInlineEnd).toBe("calc(62.5% - 8px)");
    // A quick release can arrive before the next move event or animation frame.
    pointer("pointerdown", 450);
    pointer("pointerup", 500);
    expect(saved()).toBeCloseTo(700 / 1200);
    expect(divider).toHaveAttribute("aria-valuenow", "700");
    pointer("pointerdown", 500);
    pointer("pointermove", 480);
    pointer("pointerup", 450);
    expect(saved()).toBe(0.625);
    expect(divider).toHaveAttribute("aria-valuenow", "750");
    act(() => jest.advanceTimersByTime(20));
    expect(divider).toHaveAttribute("aria-valuenow", "750");
    pointer("pointerdown", 450);
    pointer("pointermove", 800, 2);
    expect(divider).toHaveAttribute("aria-valuenow", "750");
    pointer("pointermove", 800);
    act(() => jest.advanceTimersByTime(20));
    expect(divider).toHaveAttribute("aria-valuenow", "400");
    pointer("pointercancel", 800);
    expect(saved()).toBe(0.625);
    expect(divider).toHaveAttribute("aria-valuenow", "750");
    pointer("pointerdown", 450);
    pointer("pointermove", 500);
    act(() => {
      useBuildSessionStore.getState().createSession("session-b", {
        outputPanelMode: "medium",
        mediumPanelProportion: 0.4,
      });
      useBuildSessionStore.getState().setCurrentSession("session-b");
    });
    pointer("pointerup", 500);
    expect(readOutputPanelPreferences("session-b")?.mediumPanelProportion).toBe(
      0.4
    );
    expect(saved()).toBe(0.625);
    act(() => useBuildSessionStore.getState().setCurrentSession("session-a"));
    pointer("pointerdown", 450);
    pointer("pointermove", 500);
    act(() =>
      useBuildSessionStore.getState().setCurrentOutputPanelMode("full")
    );
    pointer("pointerup", 500);
    expect(saved()).toBe(0.625);
    expect(root).toHaveAttribute("data-output-mode", "full");
  } finally {
    resize.mockRestore();
    jest.useRealTimers();
  }
});
