import { render, screen, fireEvent } from "@tests/setup/test-utils";
import PreviewSidebar from "@/app/craft/components/output-panel/PreviewSidebar";

// --- Thumbnail sidebar resizing ---
it("resizes thumbnails with quick pointer release and keyboard limits", async () => {
  render(
    <div>
      <PreviewSidebar label="Resize slide thumbnails" initialWidth={112}>
        <div />
      </PreviewSidebar>
    </div>
  );
  const divider = await screen.findByRole("separator", {
    name: "Resize slide thumbnails",
  });
  divider.setPointerCapture = jest.fn();
  divider.hasPointerCapture = () => true;
  divider.releasePointerCapture = jest.fn();
  const pointer = (type: string, clientX: number) => {
    const event = new MouseEvent(type, { bubbles: true, button: 0, clientX });
    Object.defineProperty(event, "pointerId", { value: 1 });
    fireEvent(divider, event);
  };
  pointer("pointerdown", 112);
  pointer("pointerup", 180);
  expect(divider).toHaveAttribute("aria-valuenow", "180");
  fireEvent.keyDown(divider, { key: "ArrowRight" });
  expect(divider).toHaveAttribute("aria-valuenow", "190");
  fireEvent.keyDown(divider, { key: "End" });
  expect(divider).toHaveAttribute("aria-valuenow", "320");
  fireEvent.keyDown(divider, { key: "Home" });
  expect(divider).toHaveAttribute("aria-valuenow", "88");
  pointer("pointerdown", 88);
  pointer("pointermove", 160);
  pointer("pointercancel", 250);
  expect(divider).toHaveAttribute("aria-valuenow", "160");
});

it("keeps the resized width when thumbnails are hidden and shown", () => {
  const view = (hidden: boolean) => (
    <div>
      <PreviewSidebar label="Resize thumbnails" hidden={hidden}>
        <div />
      </PreviewSidebar>
    </div>
  );
  const { rerender } = render(view(false));
  fireEvent.keyDown(screen.getByRole("separator"), { key: "ArrowRight" });
  rerender(view(true));
  expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  rerender(view(false));
  expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "154");
});
