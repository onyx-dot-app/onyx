import { act, render, screen } from "@tests/setup/test-utils";
import { ToastProvider } from "@opal/layouts/toast/components";
import { toast } from "@opal/layouts/toast/store";

afterEach(() => {
  act(() => toast.clearAll());
});

it("keeps a polite live region mounted and announces new toasts in it", () => {
  render(<ToastProvider>{null}</ToastProvider>);

  // A screen reader announces only changes to a live region that already
  // exists, so the region must be there before the first toast.
  const liveRegion = screen
    .getByTestId("toast-container")
    .querySelector('[aria-live="polite"]');
  expect(liveRegion).not.toBeNull();
  expect(liveRegion).toBeEmptyDOMElement();

  act(() => {
    toast.success("Settings saved", { duration: Infinity });
  });

  expect(liveRegion).toHaveTextContent("Settings saved");
});
