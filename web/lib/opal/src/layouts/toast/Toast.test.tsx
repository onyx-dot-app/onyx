import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import { ToastProvider, toast } from "@opal/layouts";
import { SvgRefreshCw } from "@opal/icons";

const initialWidth = window.innerWidth;

afterEach(() => {
  act(() => toast.clearAll());
  jest.restoreAllMocks();
  Object.defineProperty(window, "innerWidth", {
    value: initialWidth,
    configurable: true,
  });
});

it("wraps a narrow error and keeps its action and close control usable", async () => {
  Object.defineProperty(window, "innerWidth", {
    value: 320,
    configurable: true,
  });
  const retry = jest.fn();
  const user = setupUser();
  render(
    <ToastProvider>
      <main>Page content</main>
    </ToastProvider>
  );
  act(() => {
    toast.error("Skill file limit reached", {
      description:
        "This change exceeds the file limit. Turn off some skills, then try again.",
      duration: Infinity,
      action: { label: "Retry", icon: SvgRefreshCw, onClick: retry },
    });
  });
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent("Skill file limit reached");
  expect(screen.getByText("Skill file limit reached")).not.toHaveClass(
    "truncate"
  );
  expect(
    screen.queryByRole("button", { name: "Show the full message" })
  ).not.toBeInTheDocument();
  await user.tab();
  expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(retry).toHaveBeenCalledTimes(1);
  expect(alert).toBeInTheDocument();
  await user.tab();
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  await user.keyboard("{Enter}");
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  );
});

it("announces ordinary success without duplicating a rich caller's alert", () => {
  render(
    <ToastProvider>
      <main>Page content</main>
    </ToastProvider>
  );
  act(() => {
    toast.success("Saved");
    toast.error("Skills did not load", {
      children: <section role="alert">Review omitted skills</section>,
    });
  });
  expect(screen.getByRole("status")).toHaveTextContent("Saved");
  expect(screen.getAllByRole("alert")).toHaveLength(1);
  expect(screen.getByRole("alert")).toHaveTextContent("Review omitted skills");
});

it("lets keyboard users expand and scroll a long mobile title without losing controls", async () => {
  Object.defineProperty(window, "innerWidth", {
    value: 320,
    configurable: true,
  });
  jest
    .spyOn(HTMLElement.prototype, "scrollHeight", "get")
    .mockReturnValue(2000);
  jest.spyOn(HTMLElement.prototype, "clientHeight", "get").mockReturnValue(48);
  const user = setupUser();
  const retry = jest.fn();
  const message = "Long server error. ".repeat(200);
  render(
    <ToastProvider>
      <main>Page content</main>
    </ToastProvider>
  );
  act(() => {
    toast.error(message, {
      duration: Infinity,
      action: { label: "Retry", icon: SvgRefreshCw, onClick: retry },
    });
  });
  await user.click(
    await screen.findByRole("button", { name: "Show the full message" })
  );
  const details = screen
    .getAllByText(message.trim())
    .find((node) => node.parentElement?.tabIndex === 0)?.parentElement;
  expect(details).toHaveClass("max-h-[min(18rem,25dvh)]", "overflow-y-auto");
  await user.tab({ shift: true });
  await user.tab({ shift: true });
  expect(details).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "Retry" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(retry).toHaveBeenCalledTimes(1);
  await user.tab();
  await user.tab();
  expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
  await user.keyboard("{Enter}");
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument()
  );
});
