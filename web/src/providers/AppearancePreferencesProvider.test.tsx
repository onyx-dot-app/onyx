import { act, render, screen } from "@tests/setup/test-utils";
import { ToastProvider, toast } from "@opal/layouts";
import { AppearancePreferencesProvider } from "@/providers/AppearancePreferencesProvider";

// Past the default auto-dismiss time and the leave animation.
const LONG_WAIT_MS = 10_000;

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { preferences: { popup_dismissal: "stay_on_screen" } },
  }),
}));

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  act(() => toast.clearAll());
  jest.useRealTimers();
});

test("Stay on screen keeps default-time toasts, also ones fired before it applied", () => {
  // Fired on a cold load, before the saved preference reaches the store.
  act(() => {
    toast.info("Signed in", { dismissible: false });
  });
  render(
    <AppearancePreferencesProvider>
      <ToastProvider>{null}</ToastProvider>
    </AppearancePreferencesProvider>
  );
  act(() => {
    toast.info("Saved");
    toast.info("Copied", { duration: 1000 });
  });
  act(() => jest.advanceTimersByTime(LONG_WAIT_MS));

  // An explicit duration still applies.
  expect(screen.queryByText("Copied")).not.toBeInTheDocument();
  expect(screen.getByText("Saved")).toBeInTheDocument();
  expect(screen.getByText("Signed in")).toBeInTheDocument();

  // Each persistent toast shows a close button, even one that asked to hide it.
  const closeButtons = screen.getAllByRole("button", { name: "Close" });
  expect(closeButtons).toHaveLength(2);
  act(() => closeButtons.forEach((button) => button.click()));
  act(() => jest.advanceTimersByTime(LONG_WAIT_MS));
  expect(screen.queryByText("Saved")).not.toBeInTheDocument();
  expect(screen.queryByText("Signed in")).not.toBeInTheDocument();
});
