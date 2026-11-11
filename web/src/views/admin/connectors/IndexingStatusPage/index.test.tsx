/** The history panel scrolls into view only where it stacks under the list, the header offers Add Connector only to a global connector manager, and a row's View Errors focuses its latest run in the fleet's history when that run holds open errors, else opens the pair's history. */
import { render, screen } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { Button, Text } from "@opal/components";
import IndexingStatusPage, {
  revealHistory,
} from "@/views/admin/connectors/IndexingStatusPage";
import type { ActivityPanelProps } from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import type { ConnectorListProps } from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";
import { Permission, type IndexAttemptSnapshot } from "@/lib/types";
import { makeConnectorRow } from "@tests/setup/indexingConnectorTestUtils";

const NOW = "2026-11-03T08:00:00Z";
// A row whose error count counts its latest run's open errors.
const ERRORED_RUN: IndexAttemptSnapshot = {
  id: 77,
  status: "completed_with_errors",
  from_beginning: false,
  new_docs_indexed: 3,
  docs_removed_from_index: 0,
  total_docs_indexed: 40,
  error_msg: null,
  error_count: 3,
  open_error_count: 3,
  open_doc_error_count: 3,
  full_exception_trace: null,
  time_started: NOW,
  time_updated: NOW,
  time_finished: NOW,
  is_new_model: false,
  is_backfill: false,
};
const ROW_WITH_ERRORS = makeConnectorRow({
  cc_pair_id: 4,
  status: "indexing",
  open_error_count: 3,
  latest_index_attempt: ERRORED_RUN,
});
// Open prune or check runs count on the row, but its latest run has no open errors.
const ROW_WITH_RUN_ERRORS = makeConnectorRow({
  cc_pair_id: 6,
  open_error_count: 2,
  latest_index_attempt: {
    ...ERRORED_RUN,
    status: "success",
    error_count: 0,
    open_error_count: 0,
    open_doc_error_count: 0,
  },
});
const ROW_WITHOUT_RUN = makeConnectorRow({
  cc_pair_id: 5,
  open_error_count: 1,
});

// The list and the panel stand in as their props, so the page's wiring is what the cases see.
jest.mock("@/views/admin/connectors/IndexingStatusPage/ConnectorList", () => ({
  __esModule: true,
  default: ({ onFocusError }: ConnectorListProps) => (
    <>
      <Button onClick={() => onFocusError(ROW_WITH_ERRORS)}>View Errors</Button>
      <Button onClick={() => onFocusError(ROW_WITH_RUN_ERRORS)}>
        View Errors from other runs
      </Button>
      <Button onClick={() => onFocusError(ROW_WITHOUT_RUN)}>
        View Errors without a run
      </Button>
    </>
  ),
}));

jest.mock("@/views/admin/connectors/ConnectorDetailPage/ActivityPanel", () => ({
  __esModule: true,
  default: ({ scope, focusAttemptId }: ActivityPanelProps) => (
    <Text data-testid="history">
      {`${scope === "fleet" ? "fleet" : `pair ${scope.ccPairId}`} focus ${focusAttemptId ?? "none"}`}
    </Text>
  ),
}));

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
    expect(screen.getByRole("link", { name: "Add Connector" })).toHaveAttribute(
      "href",
      "/admin/connectors"
    );
  });

  it("is absent for a viewer who only reads connectors", () => {
    mockHeldPermission = Permission.READ_CONNECTORS;
    render(<IndexingStatusPage />);
    expect(screen.getByText("Connector Indexing Status")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Add Connector" })).toBeNull();
  });
});

describe("View Errors", () => {
  const originalFetch = global.fetch;
  beforeEach(() => {
    window.sessionStorage.clear();
    // Pending forever, so the fleet panel stays closed until the page opens it.
    global.fetch = jest.fn(
      () => new Promise<Response>(() => {})
    ) as typeof fetch;
  });
  afterEach(() => {
    global.fetch = originalFetch;
  });

  it("opens the fleet's history focused on the row's latest run", async () => {
    const user = userEvent.setup();
    render(<IndexingStatusPage />);
    expect(screen.queryByTestId("history")).toBeNull();

    await user.click(screen.getByRole("button", { name: "View Errors" }));

    expect(screen.getByTestId("history")).toHaveTextContent("fleet focus 77");
  });

  it("opens the pair's history when only prune or check runs count", async () => {
    const user = userEvent.setup();
    render(<IndexingStatusPage />);

    await user.click(
      screen.getByRole("button", { name: "View Errors from other runs" })
    );

    expect(screen.getByTestId("history")).toHaveTextContent(
      "pair 6 focus none"
    );
  });

  it("opens the pair's history for a row with no run", async () => {
    const user = userEvent.setup();
    render(<IndexingStatusPage />);

    await user.click(
      screen.getByRole("button", { name: "View Errors without a run" })
    );

    expect(screen.getByTestId("history")).toHaveTextContent(
      "pair 5 focus none"
    );
  });
});
