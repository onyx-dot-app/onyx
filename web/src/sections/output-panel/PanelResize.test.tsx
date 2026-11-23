import { useRef } from "react";
import { fireEvent, render } from "@tests/setup/test-utils";
import { useEscapeInterrupt } from "@/hooks/useEscapeInterrupt";
import { useOutputPanelWorkspace } from "@/sections/output-panel/PanelResize";

/** Craft's workspace: Escape stops a run, and restores a full panel. */
function Workspace({
  full,
  onStop,
  onRestore,
}: {
  full: boolean;
  onStop: () => void;
  onRestore: () => void;
}) {
  useEscapeInterrupt({ enabled: true, onInterrupt: onStop });
  const workspace = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  useOutputPanelWorkspace({
    workspaceRef: workspace,
    pageRef: page,
    coverFocusRef: workspace,
    mode: full ? "full" : "medium",
    proportion: 0.5,
    onResize: () => undefined,
    onRestore,
    sessionId: "session",
  });
  return (
    <div ref={workspace}>
      <p ref={page}>Workspace</p>
    </div>
  );
}

test("Escape restores a panel expanded after a run started, and does not stop the run", () => {
  const onStop = jest.fn();
  const onRestore = jest.fn();
  // The run's Escape listener is added before the panel expands
  const view = render(
    <Workspace full={false} onStop={onStop} onRestore={onRestore} />
  );
  view.rerender(<Workspace full onStop={onStop} onRestore={onRestore} />);

  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(onRestore).toHaveBeenCalledTimes(1);
  expect(onStop).not.toHaveBeenCalled();

  view.rerender(
    <Workspace full={false} onStop={onStop} onRestore={onRestore} />
  );
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(onStop).toHaveBeenCalledTimes(1);
});

test("Escape leaves a full panel alone while an IME composes or a menu is open", () => {
  const onStop = jest.fn();
  const onRestore = jest.fn();
  render(<Workspace full onStop={onStop} onRestore={onRestore} />);

  fireEvent.keyDown(document.body, { key: "Escape", isComposing: true });
  const menu = document.createElement("div");
  menu.setAttribute("role", "menu");
  // jsdom lays nothing out: a box makes the menu count as visible
  Object.defineProperty(menu, "getClientRects", {
    value: () => [{ width: 1, height: 1 }],
  });
  document.body.appendChild(menu);
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(onRestore).not.toHaveBeenCalled();

  // A hidden menu does not take Escape
  menu.hidden = true;
  fireEvent.keyDown(document.body, { key: "Escape" });
  expect(onRestore).toHaveBeenCalledTimes(1);
  menu.remove();
});

/** A workspace with a resize handle, for a session that can change. */
function ResizableWorkspace({
  sessionId,
  onResize,
}: {
  sessionId: string;
  onResize: (proportion: number) => void;
}) {
  const workspace = useRef<HTMLDivElement>(null);
  const layout = useOutputPanelWorkspace({
    workspaceRef: workspace,
    pageRef: workspace,
    coverFocusRef: workspace,
    mode: "medium",
    proportion: 0.5,
    onResize,
    onRestore: () => undefined,
    sessionId,
  });
  return (
    <div ref={workspace}>
      <div role="separator" {...layout.handleProps} />
    </div>
  );
}

describe("resizing", () => {
  // jsdom has no pointer events or pointer capture
  class TestPointerEvent extends MouseEvent {
    pointerId: number;
    constructor(type: string, init: PointerEventInit = {}) {
      super(type, init);
      this.pointerId = init.pointerId ?? 0;
    }
  }
  const pointerEvent = Object.getOwnPropertyDescriptor(window, "PointerEvent");

  beforeEach(() => {
    // A 1000px workspace: the panel's width is 1000 minus the pointer's x
    jest
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue(DOMRect.fromRect({ x: 0, y: 0, width: 1000 }));
    Object.defineProperty(window, "PointerEvent", {
      configurable: true,
      value: TestPointerEvent,
    });
  });

  afterEach(() => {
    if (pointerEvent)
      Object.defineProperty(window, "PointerEvent", pointerEvent);
    else Reflect.deleteProperty(window, "PointerEvent");
    jest.restoreAllMocks();
  });

  function renderHandle(onResize: (proportion: number) => void) {
    const view = render(
      <ResizableWorkspace sessionId="first" onResize={onResize} />
    );
    const handle = view.getByRole("separator");
    Object.assign(handle, {
      setPointerCapture: () => undefined,
      hasPointerCapture: () => false,
    });
    return { view, handle };
  }

  test("a session change during a drag cancels it, so the release saves nothing", () => {
    const onResize = jest.fn();
    const { view, handle } = renderHandle(onResize);
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 450 });
    // A back or forward shortcut opens another session mid-drag
    view.rerender(
      <ResizableWorkspace sessionId="second" onResize={onResize} />
    );
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 450 });
    expect(onResize).not.toHaveBeenCalled();
  });

  test("a release before the next frame saves the width at the release position", () => {
    const onResize = jest.fn();
    const { handle } = renderHandle(onResize);
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 400 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 420 });
    expect(onResize).toHaveBeenCalledTimes(1);
    expect(onResize).toHaveBeenLastCalledWith(0.58);
  });

  test("a cancelled drag or a lost capture saves the last pointer position", () => {
    const onResize = jest.fn();
    const { handle } = renderHandle(onResize);
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 450 });
    fireEvent.pointerCancel(handle, { pointerId: 1, clientX: 0 });
    expect(onResize).toHaveBeenLastCalledWith(0.55);

    fireEvent.pointerDown(handle, { button: 0, pointerId: 2, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 2, clientX: 420 });
    fireEvent.lostPointerCapture(handle, { pointerId: 2, clientX: 0 });
    expect(onResize).toHaveBeenLastCalledWith(0.58);
    expect(onResize).toHaveBeenCalledTimes(2);
  });

  test("a double click restores the default width, unless its second press drags the edge", () => {
    const onResize = jest.fn();
    const { handle } = renderHandle(onResize);
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 500 });
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 500 });
    fireEvent.pointerMove(handle, { pointerId: 1, clientX: 420 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 420 });
    fireEvent.doubleClick(handle);
    expect(onResize).toHaveBeenLastCalledWith(0.58);

    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 420 });
    fireEvent.pointerUp(handle, { pointerId: 1, clientX: 420 });
    fireEvent.doubleClick(handle);
    expect(onResize).toHaveBeenLastCalledWith(0.5);
  });
});
