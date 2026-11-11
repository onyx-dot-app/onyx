import { act, render, screen } from "@tests/setup/test-utils";
import { ToastProvider } from "@opal/layouts/toast/components";
import { toast } from "@opal/layouts/toast/store";

function renderProvider() {
  const { container } = render(
    <ToastProvider>
      <main />
    </ToastProvider>
  );
  return () => container.querySelector('[aria-live="polite"]');
}

describe("ToastProvider live region", () => {
  beforeEach(() => {
    jest.spyOn(console, "info").mockImplementation(() => {});
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    act(() => toast.clearAll());
    jest.restoreAllMocks();
  });

  it("keeps an empty live region mounted before any toast", () => {
    const region = renderProvider();
    expect(region()).toBeInTheDocument();
    expect(region()).toBeEmptyDOMElement();
    expect(screen.queryByTestId("toast-container")).not.toBeInTheDocument();
  });

  it("adds each toast inside the same live region", () => {
    const region = renderProvider();
    const before = region();
    act(() => {
      toast.error("Indexing failed", { description: "Connector timed out." });
    });
    expect(region()).toBe(before);
    expect(region()).toHaveTextContent("Indexing failed");
    expect(region()).toHaveTextContent("Connector timed out.");
    expect(screen.getAllByText("Indexing failed")).toHaveLength(1);
  });
});
