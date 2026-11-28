import { fireEvent, render, screen } from "@tests/setup/test-utils";
import { ChatSidePanel } from "@/sections/chat/ChatSidePanel";

interface ViewProps {
  open: boolean;
  onClose: () => void;
  shows?: string;
}

function View({ open, onClose, shows }: ViewProps) {
  return (
    <>
      <button type="button">Open</button>
      <button type="button">Switch</button>
      <ChatSidePanel open={open} onEscape={onClose} shows={shows}>
        <button type="button">Inside</button>
      </ChatSidePanel>
    </>
  );
}

test("a closed panel is inert, and closing returns focus to its opener", () => {
  const onClose = jest.fn();
  const { rerender } = render(<View open={false} onClose={onClose} />);
  const inside = screen.getByText("Inside");
  expect(inside.closest("[inert]")).not.toBeNull();

  const opener = screen.getByText("Open");
  opener.focus();
  rerender(<View open onClose={onClose} />);
  expect(inside.closest("[inert]")).toBeNull();
  // Opening moves focus into the panel.
  expect(inside.closest("[tabindex='-1']")).toBe(document.activeElement);

  fireEvent.keyDown(inside, { key: "Escape" });
  expect(onClose).toHaveBeenCalledTimes(1);

  rerender(<View open={false} onClose={onClose} />);
  expect(document.activeElement).toBe(opener);
});

test("closing returns focus to the element outside that last switched the panel", () => {
  const onClose = jest.fn();
  const { rerender } = render(
    <View open={false} onClose={onClose} shows="sources" />
  );
  const opener = screen.getByText("Open");
  const switcher = screen.getByText("Switch");
  const inside = screen.getByText("Inside");

  opener.focus();
  rerender(<View open onClose={onClose} shows="sources" />);
  switcher.focus();
  rerender(<View open onClose={onClose} shows="files" />);
  // A switch from inside the panel keeps the element outside that switched it
  inside.focus();
  rerender(<View open onClose={onClose} shows="file:report" />);

  rerender(<View open={false} onClose={onClose} shows="file:report" />);
  expect(document.activeElement).toBe(switcher);
});

test("Escape closes an open preview first, and the panel on the next press", () => {
  const onClose = jest.fn();
  render(<View open onClose={onClose} />);
  const inside = screen.getByText("Inside");

  // A preview dialog that the panel opened. Focus stays on the card in the
  // panel, and the dialog closes on Escape before the event bubbles.
  const preview = document.createElement("div");
  preview.setAttribute("role", "dialog");
  Object.defineProperty(preview, "getClientRects", {
    value: () => [{ width: 1, height: 1 }],
  });
  document.body.appendChild(preview);
  const closePreview = (event: KeyboardEvent) => {
    if (event.key === "Escape") preview.remove();
  };
  document.addEventListener("keydown", closePreview, true);
  try {
    fireEvent.keyDown(inside, { key: "Escape" });
    expect(preview.isConnected).toBe(false);
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.keyDown(inside, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  } finally {
    document.removeEventListener("keydown", closePreview, true);
  }
});

test("a panel without a reserve slides open and shut", () => {
  const { rerender } = render(
    <ChatSidePanel open={false} onEscape={jest.fn()}>
      <button type="button">Inside</button>
    </ChatSidePanel>
  );
  const panel = screen.getByText("Inside").parentElement!;
  const animates = () =>
    [...panel.classList].some((name) => name.startsWith("transition"));
  expect(animates()).toBe(false);
  rerender(
    <ChatSidePanel open onEscape={jest.fn()}>
      <button type="button">Inside</button>
    </ChatSidePanel>
  );
  expect(animates()).toBe(true);
  // jsdom has no TransitionEvent
  const endTransition = (target: Element) => {
    const event = new Event("transitionend", { bubbles: true });
    Object.defineProperty(event, "propertyName", { value: "width" });
    fireEvent(target, event);
  };
  // A child's transition does not end the panel's slide
  endTransition(screen.getByText("Inside"));
  expect(animates()).toBe(true);
  endTransition(panel);
  expect(animates()).toBe(false);
});

// A slide beside the page would lay out the page and the panel's content
// again on each frame
test("a panel with a reserve opens, closes and changes shape in one frame", () => {
  const Panel = ({
    open,
    reserve,
    covers,
  }: {
    open: boolean;
    reserve: number;
    covers: boolean;
  }) => (
    <ChatSidePanel
      open={open}
      onEscape={jest.fn()}
      reserve={reserve}
      covers={covers}
    >
      <button type="button">Inside</button>
    </ChatSidePanel>
  );
  const { rerender } = render(
    <Panel open={false} reserve={600} covers={false} />
  );
  const panel = screen.getByText("Inside").parentElement!;
  const reserve = panel.parentElement!;
  // A duration alone animates every property: CSS transition-property
  // defaults to `all`
  const animates = (element: Element) =>
    [...element.classList].some((name) =>
      /^(transition|duration-|ease-)/.test(name)
    );
  const sliding = () => animates(panel) || animates(reserve);
  expect(sliding()).toBe(false);

  rerender(<Panel open reserve={600} covers={false} />);
  expect(sliding()).toBe(false);
  expect(reserve.style.width).toBe("600px");
  expect(panel.style.width).toBe("600px");

  rerender(<Panel open reserve={700} covers />);
  expect(sliding()).toBe(false);
  expect(panel.style.width).toBe("100%");

  rerender(<Panel open={false} reserve={700} covers={false} />);
  expect(sliding()).toBe(false);
  expect(reserve.style.width).toBe("0px");
});
