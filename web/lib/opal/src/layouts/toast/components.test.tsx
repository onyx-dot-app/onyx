import { act, render, screen } from "@tests/setup/test-utils";
import { ToastProvider } from "@opal/layouts/toast/components";
import { toast } from "@opal/layouts/toast/store";

function renderProvider() {
  render(
    <ToastProvider errorAppendix="Contact support.">
      <main />
    </ToastProvider>
  );
}

describe("ToastProvider announcements", () => {
  beforeEach(() => {
    jest.spyOn(console, "info").mockImplementation(() => {});
    jest.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    act(() => toast.clearAll());
    jest.restoreAllMocks();
  });

  it("keeps empty live regions mounted before any toast", () => {
    renderProvider();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();
  });

  it("announces info politely and errors assertively", () => {
    renderProvider();
    act(() => {
      toast.info("Saved", { description: "Your changes are live." });
    });
    expect(screen.getByRole("status")).toHaveTextContent(
      "Saved. Your changes are live."
    );
    expect(screen.getByRole("alert")).toBeEmptyDOMElement();

    act(() => {
      toast.error("Indexing failed");
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Indexing failed. Contact support."
    );
  });

  it("announces a toast again when it is updated in place", () => {
    renderProvider();
    act(() => {
      toast.error("Load failed", { id: "fetch" });
    });
    act(() => {
      toast.error("Load failed again", { id: "fetch" });
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Load failed again");
  });
});
