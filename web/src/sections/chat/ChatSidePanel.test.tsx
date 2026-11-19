import { fireEvent, render, screen } from "@tests/setup/test-utils";
import { ChatSidePanel } from "@/sections/chat/ChatSidePanel";

interface ViewProps {
  open: boolean;
  onClose: () => void;
}

function View({ open, onClose }: ViewProps) {
  return (
    <>
      <button type="button">Open</button>
      <button type="button">Switch</button>
      <ChatSidePanel open={open} onEscape={onClose}>
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
