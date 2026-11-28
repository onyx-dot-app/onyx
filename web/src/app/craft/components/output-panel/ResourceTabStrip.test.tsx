import { DirectionProvider } from "@radix-ui/react-direction";
import { useState } from "react";
import { act, fireEvent } from "@testing-library/react";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import ResourceTabStrip from "@/app/craft/components/output-panel/ResourceTabStrip";
import { panelTabId, type PanelTab } from "@/app/craft/types/displayTypes";

const tabs: PanelTab[] = [
  { kind: "files" },
  { kind: "file", path: "outputs/notes.md", fileName: "notes.md" },
  { kind: "browser", id: "one", appId: null },
];
function props() {
  return {
    tabs,
    activeTabId: "files",
    onSelect: jest.fn(),
    onClose: jest.fn(),
    onReorder: jest.fn(),
    onOpenOutputs: jest.fn(),
    onOpenFiles: jest.fn(),
    onOpenBrowser: jest.fn(),
  };
}

test("arrow navigation selects and focuses a tab while Alt reorders it", () => {
  const callbacks = props();
  render(<ResourceTabStrip {...callbacks} />);
  const files = screen.getByRole("tab", { name: "All Files" });
  act(() => files.focus());
  fireEvent.keyDown(files, { key: "ArrowRight" });
  expect(callbacks.onSelect).toHaveBeenCalledWith("file:outputs/notes.md");
  expect(screen.getByRole("tab", { name: "notes.md" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("tab", { name: "notes.md" }), {
    key: "ArrowRight",
    altKey: true,
  });
  expect(callbacks.onReorder).toHaveBeenCalledWith("file:outputs/notes.md", 2);
});

test("Alt+arrow past the strip's end moves nothing and announces nothing", () => {
  const callbacks = props();
  render(<ResourceTabStrip {...callbacks} />);
  fireEvent.keyDown(screen.getByRole("tab", { name: "All Files" }), {
    key: "ArrowLeft",
    altKey: true,
  });
  expect(callbacks.onReorder).not.toHaveBeenCalled();
  expect(screen.queryByText(/^Tab moved to position/)).toBeNull();
});

test("closing the last tab focuses the plus action", async () => {
  const user = setupUser();
  const callbacks = props();
  const { rerender } = render(
    <ResourceTabStrip {...callbacks} tabs={[{ kind: "files" }]} />
  );
  await user.click(screen.getByRole("button", { name: "Close All Files" }));
  expect(callbacks.onClose).toHaveBeenCalledWith("files");
  rerender(<ResourceTabStrip {...callbacks} tabs={[]} activeTabId={null} />);
  expect(screen.getByRole("button", { name: "Open a tab" })).toHaveFocus();
});

test("plus offers Files and Browser and opens a fresh Browser", async () => {
  const user = setupUser();
  const callbacks = props();
  render(<ResourceTabStrip {...callbacks} />);
  await user.click(screen.getByRole("button", { name: "Open a tab" }));
  await user.click(await screen.findByRole("menuitem", { name: "Apps" }));
  expect(callbacks.onOpenBrowser).toHaveBeenCalledTimes(1);
});

test("reverses keyboard selection and reorder in RTL", () => {
  const callbacks = props();
  render(
    <DirectionProvider dir="rtl">
      <ResourceTabStrip {...callbacks} />
    </DirectionProvider>
  );
  const notes = screen.getByRole("tab", { name: "notes.md" });
  fireEvent.keyDown(notes, { key: "ArrowLeft" });
  expect(callbacks.onSelect).toHaveBeenCalledWith("browser:one");
  fireEvent.keyDown(notes, { key: "ArrowLeft", altKey: true });
  expect(callbacks.onReorder).toHaveBeenCalledWith("file:outputs/notes.md", 2);
});

test("tab labels support keyboard activation", () => {
  const callbacks = props();
  render(<ResourceTabStrip {...callbacks} />);
  const notes = screen.getByRole("tab", { name: "notes.md" });
  fireEvent.keyDown(notes, { key: "Enter" });
  fireEvent.keyDown(notes, { key: " " });
  expect(callbacks.onSelect).toHaveBeenNthCalledWith(
    1,
    "file:outputs/notes.md"
  );
  expect(callbacks.onSelect).toHaveBeenNthCalledWith(
    2,
    "file:outputs/notes.md"
  );
});

test("the whole pill selects once while its close action only closes", () => {
  const callbacks = props();
  render(<ResourceTabStrip {...callbacks} />);
  const notes = screen.getByRole("tab", { name: "notes.md" });
  const pill = notes.closest(".group");
  if (!pill) throw new Error("Missing resource pill");
  fireEvent.click(pill);
  fireEvent.click(notes);
  expect(callbacks.onSelect).toHaveBeenCalledTimes(2);
  expect(callbacks.onSelect).toHaveBeenLastCalledWith("file:outputs/notes.md");
  fireEvent.click(screen.getByRole("button", { name: "Close notes.md" }));
  expect(callbacks.onClose).toHaveBeenCalledWith("file:outputs/notes.md");
  expect(callbacks.onSelect).toHaveBeenCalledTimes(2);
});

test("disabled resource tabs reject close, selection, and keyboard reorder", () => {
  const callbacks = props();
  render(<ResourceTabStrip {...callbacks} disabled />);
  const notes = screen.getByRole("tab", { name: "notes.md" });
  fireEvent.click(notes);
  const pill = notes.closest(".group");
  if (!pill) throw new Error("Missing resource pill");
  fireEvent.click(pill);
  fireEvent.click(screen.getByRole("button", { name: "Close notes.md" }));
  fireEvent.keyDown(notes, { key: "Enter" });
  fireEvent.keyDown(notes, { key: "ArrowRight", altKey: true });
  expect(callbacks.onSelect).not.toHaveBeenCalled();
  expect(callbacks.onClose).not.toHaveBeenCalled();
  expect(callbacks.onReorder).not.toHaveBeenCalled();
});

test("closing an inactive tab restores focus to the selected tab", async () => {
  const callbacks = props();
  const user = setupUser();
  const { rerender } = render(<ResourceTabStrip {...callbacks} />);
  await user.click(screen.getByRole("button", { name: "Close notes.md" }));
  expect(callbacks.onClose).toHaveBeenCalledWith("file:outputs/notes.md");
  rerender(
    <ResourceTabStrip
      {...callbacks}
      tabs={tabs.filter((tab) => tab.kind !== "file")}
    />
  );
  expect(screen.getByRole("tab", { name: "All Files" })).toHaveFocus();
});

// After a drag ends, dnd-kit stops document clicks for 50ms. The fake clock
// ends that window here, so it cannot swallow a later click in this test or
// the next one.
function endDrag(end: () => void) {
  jest.useFakeTimers();
  try {
    end();
    act(() => jest.advanceTimersByTime(50));
  } finally {
    jest.useRealTimers();
  }
}

function renderDraggableTabs(
  direction: "ltr" | "rtl" = "ltr",
  fileWidth = 100
) {
  const callbacks = props();
  const onReorder = callbacks.onReorder;
  function Harness() {
    const [ordered, setOrdered] = useState(tabs);
    return (
      <ResourceTabStrip
        {...callbacks}
        tabs={ordered}
        onClose={(id) => {
          callbacks.onClose(id);
          setOrdered((current) =>
            current.filter((tab) => panelTabId(tab) !== id)
          );
        }}
        onReorder={(id, index) => {
          onReorder(id, index);
          setOrdered((current) => {
            const source = current.findIndex((tab) => panelTabId(tab) === id);
            const next = [...current];
            const [moved] = next.splice(source, 1);
            if (moved) next.splice(index, 0, moved);
            return next;
          });
        }}
      />
    );
  }
  render(
    <DirectionProvider dir={direction}>
      <Harness />
    </DirectionProvider>
  );
  const list = screen.getByRole("tablist");
  list.style.overflowX = "auto";
  Object.defineProperty(list, "clientWidth", { value: 200 + fileWidth });
  Object.defineProperty(list, "scrollWidth", { value: 200 + fileWidth });
  function bounds(left: number, width = 100): DOMRect {
    return {
      x: left,
      y: 0,
      left,
      top: 0,
      right: left + width,
      bottom: 22,
      width,
      height: 22,
      toJSON: () => ({}),
    };
  }
  jest
    .spyOn(list, "getBoundingClientRect")
    .mockReturnValue(bounds(0, 200 + fileWidth));
  for (const tab of screen.getAllByRole("tab")) {
    const pill = tab.closest<HTMLDivElement>(".group");
    if (!pill) throw new Error("Missing tab pill");
    jest.spyOn(pill, "getBoundingClientRect").mockImplementation(() => {
      const currentTabs = screen.getAllByRole("tab");
      const index = currentTabs.indexOf(tab);
      const preceding =
        direction === "rtl"
          ? currentTabs.slice(index + 1)
          : currentTabs.slice(0, index);
      function width(element: HTMLElement) {
        return element.getAttribute("aria-label") === "notes.md"
          ? fileWidth
          : 100;
      }
      return bounds(
        preceding.reduce((left, element) => left + width(element), 0),
        width(tab)
      );
    });
  }
  function mouse(type: string, target: HTMLElement, clientX: number) {
    const fire = () =>
      fireEvent(
        target,
        new MouseEvent(type, { bubbles: true, clientX, button: 0 })
      );
    if (type === "mouseup") endDrag(fire);
    else fire();
  }
  return { list, mouse, ...callbacks };
}

test.each([15, 85])(
  "previews and reverses a drag grabbed at %i px, committing only on release",
  async (grab) => {
    const { list, mouse, onReorder, onSelect, onClose } = renderDraggableTabs();
    const files = screen.getByRole("tab", { name: "All Files" });
    mouse("mousedown", files, grab);
    mouse("mousemove", list, grab + 7);
    mouse("mousemove", list, grab + 60);
    await act(async () => {});
    expect(onReorder).not.toHaveBeenCalled();
    const notesPill = screen
      .getByRole("tab", { name: "notes.md" })
      .closest(".group");
    expect(notesPill).toHaveStyle({
      transform: "translate3d(-100px, 0px, 0)",
    });
    mouse("mousemove", list, grab);
    await act(async () => {});
    expect(onReorder).not.toHaveBeenCalled();
    expect(notesPill).toHaveStyle({
      transform: "translate3d(0px, 0px, 0)",
    });
    mouse("mousemove", list, grab + 60);
    await act(async () => {});
    mouse("mouseup", list, grab + 60);
    expect(onReorder).toHaveBeenCalledTimes(1);
    expect(onReorder).toHaveBeenCalledWith("files", 1);
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "notes.md",
      "All Files",
      "Apps",
    ]);
    fireEvent.click(screen.getByRole("tab", { name: "notes.md" }), {
      detail: 1,
    });
    expect(onSelect).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByRole("tab", { name: "notes.md" }), {
      key: "Enter",
    });
    expect(onSelect).toHaveBeenCalledWith("file:outputs/notes.md");
  }
);

test("outward dragging on a strip without overflow cannot scroll its tabs away", async () => {
  const { list, mouse, onReorder } = renderDraggableTabs();
  const apps = screen.getByRole("tab", { name: "Apps" });
  mouse("mousedown", apps, 285);
  mouse("mousemove", list, 292);
  mouse("mousemove", list, 800);
  await act(async () => {});
  expect(apps.closest(".group")).toHaveStyle({
    transform: "translate3d(0px, 0px, 0)",
  });
  expect(list.scrollLeft).toBe(0);
  mouse("mouseup", list, 800);
  expect(onReorder).not.toHaveBeenCalled();
});

test("successive closes leave no sorting transforms on remaining tabs", async () => {
  renderDraggableTabs();
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close notes.md" }));
  await user.click(screen.getByRole("button", { name: "Close Apps" }));
  expect(screen.getAllByRole("tab")).toHaveLength(1);
  const remaining = screen
    .getByRole("tab", { name: "All Files" })
    .closest<HTMLDivElement>(".group");
  expect(remaining?.style.transform).toBe("");
  expect(remaining?.style.transition).not.toContain("180ms");
});

test("cancelling a drag clears its preview and keeps the original order", async () => {
  const { list, mouse, onReorder } = renderDraggableTabs();
  const files = screen.getByRole("tab", { name: "All Files" });
  mouse("mousedown", files, 50);
  mouse("mousemove", list, 57);
  mouse("mousemove", list, 110);
  await act(async () => {});
  endDrag(() => fireEvent.keyDown(document, { key: "Escape", code: "Escape" }));
  expect(onReorder).not.toHaveBeenCalled();
  expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
    "All Files",
    "notes.md",
    "Apps",
  ]);
  for (const tab of screen.getAllByRole("tab")) {
    expect(tab.closest<HTMLDivElement>(".group")?.style.transform).toBe("");
  }
});

test("mouse sorting in RTL moves neighbors right and commits the logical destination", async () => {
  const { list, mouse, onReorder } = renderDraggableTabs("rtl");
  const files = screen.getByRole("tab", { name: "All Files" });
  mouse("mousedown", files, 250);
  mouse("mousemove", list, 243);
  mouse("mousemove", list, 190);
  await act(async () => {});
  expect(
    screen.getByRole("tab", { name: "notes.md" }).closest(".group")
  ).toHaveStyle({ transform: "translate3d(100px, 0px, 0)" });
  mouse("mouseup", list, 190);
  expect(onReorder).toHaveBeenCalledWith("files", 1);
});

test("sorting across unequal widths never scales the dragged pill or its neighbors", async () => {
  const { list, mouse, onReorder } = renderDraggableTabs("ltr", 180);
  const files = screen.getByRole("tab", { name: "All Files" });
  mouse("mousedown", files, 50);
  mouse("mousemove", list, 57);
  mouse("mousemove", list, 130);
  await act(async () => {});
  for (const tab of screen.getAllByRole("tab")) {
    expect(
      tab.closest<HTMLDivElement>(".group")?.style.transform
    ).not.toContain("scale");
  }
  mouse("mousemove", list, 50);
  await act(async () => {});
  expect(onReorder).not.toHaveBeenCalled();
  mouse("mousemove", list, 130);
  await act(async () => {});
  mouse("mouseup", list, 130);
  expect(onReorder).toHaveBeenCalledWith("files", 1);
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Close notes.md" }));
  expect(screen.queryByRole("tab", { name: "notes.md" })).toBeNull();
  for (const tab of screen.getAllByRole("tab")) {
    expect(tab.closest<HTMLDivElement>(".group")?.style.transform).toBe("");
  }
});

test("plus opens Outputs and the tab has a clear label", async () => {
  const user = setupUser();
  const callbacks = props();
  render(
    <ResourceTabStrip
      {...callbacks}
      tabs={[{ kind: "outputs" }]}
      activeTabId="outputs"
    />
  );
  expect(screen.getByRole("tab", { name: "Outputs" })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Open a tab" }));
  await user.click(await screen.findByRole("menuitem", { name: "Outputs" }));
  expect(callbacks.onOpenOutputs).toHaveBeenCalledTimes(1);
});

// Panel mode owns popover lifetime
test("closes its menu across panel mode changes without restoring an old open state", async () => {
  const user = setupUser();
  const callbacks = props();
  const { rerender } = render(
    <ResourceTabStrip {...callbacks} panelMode="medium" />
  );
  await user.click(screen.getByRole("button", { name: "Open a tab" }));
  expect(screen.getByRole("menu")).toBeVisible();
  rerender(<ResourceTabStrip {...callbacks} panelMode="closed" />);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  rerender(<ResourceTabStrip {...callbacks} panelMode="medium" />);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open a tab" }));
  expect(screen.getByRole("menu")).toBeVisible();
});

test("closing an active tab focuses the committed MRU selection instead of its neighbor", async () => {
  const callbacks = props();
  const user = setupUser();
  const { rerender } = render(
    <ResourceTabStrip {...callbacks} activeTabId="browser:one" />
  );
  await user.click(screen.getByRole("button", { name: "Close Apps" }));
  rerender(
    <ResourceTabStrip
      {...callbacks}
      tabs={tabs.slice(0, 2)}
      activeTabId="files"
    />
  );
  expect(screen.getByRole("tab", { name: "All Files" })).toHaveFocus();
  expect(screen.getByRole("tab", { name: "notes.md" })).not.toHaveFocus();
});
