/** The status page's connector list: status pills in rank order with one running pill, foldable source groups with full counts, and the error button's focus request. */
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import {
  ConnectorCredentialPairStatus,
  type IndexingConnectorRow,
  type IndexingConnectorsResponse,
} from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";
import ConnectorList from "@/views/admin/connectors/IndexingStatusPage/ConnectorList";
import englishMessages from "@/i18n/messages/en.json";

const CONNECTORS_PATH = "/api/manage/admin/index-monitoring/connectors";
const NOW = new Date().toISOString();

/** The English message at `path`. A missing key fails the test. */
function copy(path: string): string {
  const raw = path
    .split(".")
    .reduce<unknown>(
      (node, key) =>
        node !== null && typeof node === "object"
          ? (node as Record<string, unknown>)[key]
          : undefined,
      englishMessages
    );
  expect({ key: path, type: typeof raw }).toEqual({
    key: path,
    type: "string",
  });
  return raw as string;
}

const LIST = "admin.indexing.list";

function row(
  id: number,
  name: string,
  source: ValidSources,
  overrides: Partial<IndexingConnectorRow> = {}
): IndexingConnectorRow {
  return {
    cc_pair_id: id,
    name,
    source,
    access_type: "public",
    cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
    status: "indexed",
    creator_email: null,
    creator_name: null,
    docs_indexed: 100 + id,
    last_success: NOW,
    latest_index_attempt: null,
    open_error_count: 0,
    group_count: 0,
    group_names: [],
    queue_position: null,
    permissions: { operate: true },
    ...overrides,
  } as IndexingConnectorRow;
}

// Ranked by the API, so two sources interleave on the page.
const SALES = row(1, "Sales inbox", ValidSources.Gmail, {
  status: "failed",
  open_error_count: 4,
});
const ENGINEERING = row(2, "Engineering drive", ValidSources.GoogleDrive);
const SUPPORT = row(3, "Support inbox", ValidSources.Gmail);

const STATUS_COUNTS = {
  indexing: 2,
  syncing: 7,
  failed: 1,
  deleting: 0,
  scheduled: 3,
  indexed: 5,
  paused: 4,
};

/** One page that holds part of each source. The counts span every page. */
const PAGE = {
  items: [SALES, ENGINEERING, SUPPORT],
  total_items: 3,
  status_counts: STATUS_COUNTS,
  // Confluence matches on another page only, so this page draws no Confluence group.
  source_counts: { gmail: 3, google_drive: 5, confluence: 2 },
  federated_connectors: [],
} as unknown as IndexingConnectorsResponse;

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const realFetch = global.fetch;
beforeEach(() => {
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname === CONNECTORS_PATH) {
      return Promise.resolve(jsonResponse(PAGE));
    }
    return new Promise<Response>(() => {});
  }) as typeof fetch;
});
afterEach(() => {
  global.fetch = realFetch;
});

function renderList(onFocusError = jest.fn()) {
  render(
    <ConnectorList
      onViewLogs={jest.fn()}
      onFocusError={onFocusError}
      onFocusChange={jest.fn()}
    />
  );
  return { onFocusError };
}

async function loaded() {
  await screen.findByTestId(`indexing-connector-${SALES.cc_pair_id}`);
}

const GROUP_LABEL = /^(Gmail|Google Drive|Confluence) \(\d+\)$/;

/** Every source divider label, in page order. */
function groupLabels(): HTMLElement[] {
  return screen.getAllByText(GROUP_LABEL);
}

/** The divider label nearest above `element`. */
function groupOf(element: HTMLElement): string | null {
  let found: string | null = null;
  for (const label of groupLabels()) {
    if (
      label.compareDocumentPosition(element) & Node.DOCUMENT_POSITION_FOLLOWING
    ) {
      found = label.textContent;
    }
  }
  return found;
}

/** Hidden from the reader: inside a closed fold or any hidden ancestor. */
function isHidden(element: HTMLElement): boolean {
  return element.closest('[aria-hidden="true"], [inert], [hidden]') !== null;
}

describe("ConnectorList", () => {
  it("AC-4: shows one size-24 status tag per state with connectors, in rank order, and no errors pill", async () => {
    renderList();
    await loaded();

    // Rows tag at 20, so the size-24 tags are the toolbar's pills.
    const pills = Array.from(
      document.querySelectorAll<HTMLElement>('.opal-badge[data-size="6"]')
    );
    const counts = pills.map((pill) =>
      Number((pill.textContent ?? "").replace(/[^\d]/g, ""))
    );
    // running (indexing + syncing), failed, (deleting has none), scheduled, indexed, paused
    expect(counts).toEqual([9, 1, 3, 5, 4]);
  });

  it("D-98: one running pill counts indexing plus syncing and names both counts", async () => {
    renderList();
    await loaded();

    const running = screen.getByRole("button", {
      name: "2 indexing, 7 syncing",
    });
    expect(running).toHaveTextContent(/^9$/);
    expect(running).toHaveAttribute("aria-pressed", "false");
    expect(
      screen.queryByRole("button", { name: /connectors? (indexing|syncing)$/ })
    ).not.toBeInTheDocument();
  });

  it("AC-5: draws one divider per source on the page with the full count from source_counts", async () => {
    copy(`${LIST}.sourceGroup`);
    renderList();
    await loaded();

    const labels = groupLabels().map((label) => label.textContent);
    expect(labels).toHaveLength(2);
    expect(new Set(labels)).toEqual(new Set(["Gmail (3)", "Google Drive (5)"]));
    expect(screen.queryByText(/^Confluence \(/)).not.toBeInTheDocument();
  });

  it("AC-5: keeps each row under its source's divider in API order", async () => {
    renderList();
    await loaded();

    const sales = screen.getByTestId(`indexing-connector-${SALES.cc_pair_id}`);
    const support = screen.getByTestId(
      `indexing-connector-${SUPPORT.cc_pair_id}`
    );
    const engineering = screen.getByTestId(
      `indexing-connector-${ENGINEERING.cc_pair_id}`
    );
    expect(groupOf(sales)).toBe("Gmail (3)");
    expect(groupOf(support)).toBe("Gmail (3)");
    expect(groupOf(engineering)).toBe("Google Drive (5)");
    expect(
      sales.compareDocumentPosition(support) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("AC-5: a divider is open by default and folds its rows, keeping its count", async () => {
    renderList();
    await loaded();
    const sales = screen.getByTestId(`indexing-connector-${SALES.cc_pair_id}`);
    const engineering = screen.getByTestId(
      `indexing-connector-${ENGINEERING.cc_pair_id}`
    );
    expect(isHidden(sales)).toBe(false);

    await setupUser().click(screen.getByText("Gmail (3)"));

    await waitFor(() => expect(isHidden(sales)).toBe(true));
    expect(
      isHidden(screen.getByTestId(`indexing-connector-${SUPPORT.cc_pair_id}`))
    ).toBe(true);
    expect(screen.getByText("Gmail (3)")).toBeInTheDocument();
    expect(isHidden(engineering)).toBe(false);
  });

  it("AC-2: a row's View Errors asks the page to focus that connector's errors", async () => {
    const { onFocusError } = renderList();
    await loaded();

    await setupUser().click(
      screen.getByRole("button", { name: copy(`${LIST}.actions.viewErrors`) })
    );

    expect(onFocusError).toHaveBeenCalledTimes(1);
    expect(onFocusError).toHaveBeenCalledWith(
      expect.objectContaining({ cc_pair_id: SALES.cc_pair_id })
    );
  });
});
