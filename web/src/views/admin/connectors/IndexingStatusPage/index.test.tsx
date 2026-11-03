/** The history panel scrolls into view only where it stacks under the list, and the header offers Add Connector only to a global connector manager. */
import { render, screen } from "@tests/setup/test-utils";
import IndexingStatusPage, {
  revealHistory,
} from "@/views/admin/connectors/IndexingStatusPage";
import { Permission } from "@/lib/types";

// The one permission the viewer holds globally, so a gate on any other permission fails the cases below.
let mockHeldPermission: Permission | null = null;
jest.mock("@/lib/permissions/hooks", () => ({
  ...jest.requireActual("@/lib/permissions/hooks"),
  usePermissionAuthority: (permission: Permission) => ({
    isGlobalHolder: permission === mockHeldPermission,
    isScopedManager: false,
  }),
}));

jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
    refresh: jest.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/admin/indexing-status",
}));

/** A panel in a body row laid out as a row beside the column, or stacked as a column. */
function panel(direction: "row" | "column"): HTMLDivElement {
  const row = document.createElement("div");
  row.style.flexDirection = direction;
  const element = document.createElement("div");
  element.scrollIntoView = jest.fn();
  row.appendChild(element);
  return element;
}

describe("revealHistory", () => {
  it("scrolls the panel into view where the body row stacks", () => {
    const element = panel("column");
    revealHistory(element);
    expect(element.scrollIntoView).toHaveBeenCalledWith({
      block: "start",
      behavior: "smooth",
    });
  });

  it("leaves the page alone where the panel sits beside the list", () => {
    const element = panel("row");
    revealHistory(element);
    expect(element.scrollIntoView).not.toHaveBeenCalled();
  });

  it("ignores the panel unmounting", () => {
    expect(() => revealHistory(null)).not.toThrow();
  });
});

describe("Add Connector", () => {
  const originalFetch = global.fetch;
  afterEach(() => {
    global.fetch = originalFetch;
  });

  beforeEach(() => {
    // Pending forever, so the page stays on its loaders and only the header matters.
    global.fetch = jest.fn(
      () => new Promise<Response>(() => {})
    ) as typeof fetch;
  });

  it("shows for a global connector manager", () => {
    mockHeldPermission = Permission.MANAGE_CONNECTORS;
    render(<IndexingStatusPage />);
    expect(
      screen.getByRole("link", { name: "Add Connector" })
    ).toBeInTheDocument();
  });

  it("is absent for a viewer who only reads connectors", () => {
    mockHeldPermission = Permission.READ_CONNECTORS;
    render(<IndexingStatusPage />);
    expect(screen.getByText("Connector Indexing Status")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add Connector" })).toBeNull();
  });
});
