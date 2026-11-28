import { fireEvent, render, screen, setupUser } from "@tests/setup/test-utils";
import { useGridNavigation } from "@opal/hooks";

function Grid() {
  const { ref } = useGridNavigation({ itemSelector: "[data-item]" });
  return (
    <div ref={ref} data-testid="grid">
      <div data-item="" role="button" tabIndex={0} aria-label="Card">
        <button type="button">Settings</button>
      </div>
    </div>
  );
}

it("Tab to a control inside an item returns to keyboard mode", async () => {
  const user = setupUser();
  render(<Grid />);
  const grid = screen.getByTestId("grid");
  await user.tab();
  expect(screen.getByLabelText("Card")).toHaveFocus();
  fireEvent.pointerMove(grid);
  expect(grid).toHaveAttribute("data-opal-nav-mode", "pointer");
  await user.tab();
  expect(screen.getByRole("button", { name: "Settings" })).toHaveFocus();
  expect(grid).toHaveAttribute("data-opal-nav-mode", "keyboard");
});
