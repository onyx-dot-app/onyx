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
