/** An expanded connector row: the connector page's Time, Types and Status filters, six runs with running ones first, and View All Runs into the Indexing tab. */
import {
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { SvgDocFile } from "@opal/icons";
import {
  ConnectorCredentialPairStatus,
  type CCPairRun,
  type CCPairRunsResponse,
  type IndexingConnectorRow,
} from "@/lib/connectors/types";
import { ValidSources } from "@/lib/connectors/types/source";
import ConnectorRow from "@/views/admin/connectors/IndexingStatusPage/ConnectorRow";
import englishMessages from "@/i18n/messages/en.json";

const mockPush = jest.fn();
jest.mock("next/navigation", () => ({
  ...jest.requireActual("next/navigation"),
  useRouter: () => ({
    push: mockPush,
    replace: jest.fn(),
    prefetch: jest.fn(),
    back: jest.fn(),
    refresh: jest.fn(),
  }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/admin/indexing/status",
}));

const CC_PAIR_ID = 7;
const NOW = Date.now();
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const RUNS_PATH = `/api/manage/admin/cc-pair/${CC_PAIR_ID}/runs`;

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

const RUNS = "admin.connector.runs";
const LIST = "admin.indexing.list";
const VIEW_ALL_RUNS = `${LIST}.actions.viewAllRuns`;
const MD_HEIGHT = "h-(--height-line-h3-section)";

function isoAgo(ms: number): string {
  return new Date(NOW - ms).toISOString();
}

function indexRun(
  id: number,
  agoMs: number,
  status: "success" | "in_progress" | "failed" = "success"
): CCPairRun {
  const finished = status === "in_progress" ? null : isoAgo(agoMs - MINUTE_MS);
  return {
    kind: "indexing",
    time_created: isoAgo(agoMs),
    resolved_at: null,
    superseded: false,
    is_retry: false,
    attempt: {
      id,
      status,
      from_beginning: false,
      new_docs_indexed: 10,
      docs_removed_from_index: 0,
      total_docs_indexed: 10,
      error_msg: status === "failed" ? "boom" : null,
      error_count: 0,
      open_error_count: 0,
      open_doc_error_count: 0,
      full_exception_trace: null,
      time_started: isoAgo(agoMs),
      time_updated: finished ?? isoAgo(0),
      time_finished: finished,
      is_new_model: false,
      is_backfill: false,
    },
  } as CCPairRun;
}

// One long run started before the nine newest finished runs, so the newest page alone would miss it.
const RUNNING = indexRun(100, 5 * HOUR_MS, "in_progress");
const FINISHED = Array.from({ length: 9 }, (_, index) =>
  indexRun(200 + index, (index + 1) * 10 * MINUTE_MS)
);
const FAILED = indexRun(300, 30 * MINUTE_MS, "failed");

const ROW = {
  cc_pair_id: CC_PAIR_ID,
  name: "Sales Mailbox",
  source: ValidSources.Gmail,
  access_type: "public",
  cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
  status: "indexing",
  creator_email: null,
  creator_name: null,
  docs_indexed: 42918,
  last_success: isoAgo(HOUR_MS),
  latest_index_attempt: RUNNING.attempt,
  open_error_count: 0,
  group_count: 0,
  group_names: [],
  queue_position: null,
  permissions: { operate: true },
} as unknown as IndexingConnectorRow;

function runsResponse(items: CCPairRun[], total = items.length) {
  return {
    items,
    total_items: total,
    kinds: ["indexing", "doc_permission_sync", "group_sync"],
    status_counts: { running: 1, succeeded: 9, failed: 1, canceled: 0 },
  } as unknown as CCPairRunsResponse;
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

/** Every runs request the row made, as parsed URLs. */
let runsRequests: URL[] = [];

/** Serves the pair's runs feed by its filters and page size, newest first. Anything else stays pending. */
function stubRuns() {
  runsRequests = [];
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname !== RUNS_PATH) return new Promise<Response>(() => {});
    runsRequests.push(url);
    const groups = url.searchParams.getAll("status_groups");
    const kinds = url.searchParams.getAll("kinds");
    const pageSize = Number(url.searchParams.get("page_size") ?? "10");
    let items: CCPairRun[];
    if (kinds.length > 0 && !kinds.includes("indexing")) {
      items = [];
    } else if (groups.length === 0) {
      items = [...FINISHED.slice(0, 2), FAILED, ...FINISHED.slice(2), RUNNING];
    } else {
      items = [
        ...(groups.includes("running") ? [RUNNING] : []),
        ...(groups.includes("succeeded") ? FINISHED : []),
        ...(groups.includes("failed") ? [FAILED] : []),
      ];
    }
    return Promise.resolve(
      jsonResponse(runsResponse(items.slice(0, pageSize), items.length))
    );
  }) as typeof fetch;
}

const realFetch = global.fetch;
const realScrollIntoView = Element.prototype.scrollIntoView;
beforeEach(() => {
  Element.prototype.scrollIntoView = jest.fn();
  mockPush.mockReset();
  stubRuns();
});
afterEach(() => {
  global.fetch = realFetch;
  Element.prototype.scrollIntoView = realScrollIntoView;
});

function renderExpanded(row: IndexingConnectorRow = ROW) {
  const onToggle = jest.fn();
  render(
    <ConnectorRow
      row={row}
      expanded
      onToggle={onToggle}
      onViewLogs={jest.fn()}
      onFocusError={jest.fn()}
      dimmed={false}
      onFocusChange={jest.fn()}
    />
  );
  return { onToggle };
}

async function runLines(count: number): Promise<HTMLElement[]> {
  await waitFor(() =>
    expect(screen.getAllByTestId("run-row")).toHaveLength(count)
  );
  return screen.getAllByTestId("run-row");
}

/** Waits for the run list to load, whatever its length. */
async function anyRuns(): Promise<void> {
  await screen.findAllByTestId("run-row");
}

function isDisabled(control: HTMLElement): boolean {
  if (control.hasAttribute("disabled")) return true;
  return control.closest('[aria-disabled="true"]') !== null;
}

function sizedBox(control: HTMLElement): HTMLElement {
  if (control.classList.contains("interactive-container")) return control;
  const inner = control.querySelector<HTMLElement>(".interactive-container");
  expect(inner).not.toBeNull();
  return inner!;
}

/** The Time filter's trigger, whichever window it shows. */
function timeFilter(): HTMLElement {
  const labels = ["all", "h1", "h24", "d7", "d30"].map((id) =>
    copy(`${RUNS}.window.${id}`)
  );
  const matches = screen
    .getAllByRole("button")
    .filter((button) =>
      labels.some((label) => button.textContent?.trim() === label)
    );
  expect(matches).toHaveLength(1);
  return matches[0]!;
}

async function pick(trigger: HTMLElement, option: string) {
  const user = setupUser();
  await user.click(trigger);
  await user.click(await screen.findByRole("option", { name: option }));
}

describe("ConnectorRow expanded", () => {
  it("AC-6: lists six runs, the running run first, then the newest", async () => {
    renderExpanded();

    const lines = await runLines(6);
    expect(lines[0]!.querySelector('svg[role="status"]')).not.toBeNull();
    for (const line of lines.slice(1)) {
      expect(line.querySelector('svg[role="status"]')).toBeNull();
    }
  });

  it("AC-6: the header holds Time, Types and Status filters and no search", async () => {
    renderExpanded();
    await anyRuns();

    expect(
      screen.queryByPlaceholderText(copy(`${RUNS}.search.placeholder`))
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    timeFilter();
    expect(
      screen.getByRole("button", { name: copy(`${RUNS}.kinds.all`) })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: copy(`${RUNS}.statusGroups.all`) })
    ).toBeInTheDocument();
  });

  it("AC-6: the Status filter narrows the runs feed by status group", async () => {
    renderExpanded();
    await anyRuns();

    await pick(
      screen.getByRole("button", { name: copy(`${RUNS}.statusGroups.all`) }),
      copy(`${RUNS}.statusGroups.failed`)
    );

    await waitFor(() =>
      expect(
        runsRequests.some(
          (url) => url.searchParams.getAll("status_groups").join() === "failed"
        )
      ).toBe(true)
    );
    await runLines(1);
  });

  it("AC-6: the Types filter narrows the runs feed by run kind", async () => {
    renderExpanded();
    await anyRuns();

    await pick(
      screen.getByRole("button", { name: copy(`${RUNS}.kinds.all`) }),
      copy(`${RUNS}.kinds.doc_permission_sync`)
    );

    await waitFor(() =>
      expect(
        runsRequests.some(
          (url) =>
            url.searchParams.getAll("kinds").join() === "doc_permission_sync"
        )
      ).toBe(true)
    );
  });

  it("AC-6: the Time filter starts the runs feed at the picked window", async () => {
    renderExpanded();
    await anyRuns();

    await pick(timeFilter(), copy(`${RUNS}.window.d7`));

    const weekAgo = NOW - 7 * 24 * HOUR_MS;
    await waitFor(() =>
      expect(
        runsRequests.some((url) => {
          const since = url.searchParams.get("since");
          return (
            since !== null &&
            Math.abs(Date.parse(since) - weekAgo) < 2 * HOUR_MS
          );
        })
      ).toBe(true)
    );
  });

  it("AC-6: View All Runs opens the connector page on its Indexing tab", async () => {
    renderExpanded();
    await anyRuns();

    const target = `/admin/connector/${CC_PAIR_ID}?tab=indexing`;
    const link = screen.queryByRole("link", { name: copy(VIEW_ALL_RUNS) });
    if (link !== null) {
      expect(link).toHaveAttribute("href", target);
      return;
    }
    await setupUser().click(
      screen.getByRole("button", { name: copy(VIEW_ALL_RUNS) })
    );
    expect(mockPush).toHaveBeenCalledWith(target);
  });

  it("AC-6: Pause and View Logs sit in the header as 28 px buttons, View Logs with SvgDocFile", async () => {
    const { container } = render(<SvgDocFile size={16} />);
    const docFile = Array.from(container.querySelectorAll("path")).map((path) =>
      path.getAttribute("d")
    );
    renderExpanded();
    await anyRuns();

    const pause = screen.getByRole("button", {
      name: copy(`${LIST}.actions.pause`),
    });
    const logs = screen.getAllByRole("button", {
      name: copy(`${RUNS}.actions.logs`),
    });
    // The header's View Logs is the one outside the run lines.
    const headerLogs = logs.filter(
      (button) => button.closest('[data-testid="run-row"]') === null
    );
    expect(headerLogs).toHaveLength(1);
    expect(sizedBox(pause)).toHaveClass(MD_HEIGHT);
    expect(sizedBox(headerLogs[0]!)).toHaveClass(MD_HEIGHT);
    expect(
      Array.from(headerLogs[0]!.querySelectorAll("path")).map((path) =>
        path.getAttribute("d")
      )
    ).toEqual(docFile);
  });

  it("AC-8: without operate, Pause is disabled while View Details and View All Runs stay", async () => {
    const { onToggle } = renderExpanded({
      ...ROW,
      permissions: { operate: false },
    } as IndexingConnectorRow);
    await anyRuns();

    expect(
      isDisabled(screen.getByLabelText(copy(`${LIST}.actions.pause`)))
    ).toBe(true);
    const viewAll = within(document.body).getByText(copy(VIEW_ALL_RUNS));
    expect(isDisabled(viewAll)).toBe(false);
    const hide = screen.getByRole("button", {
      name: copy(`${LIST}.actions.collapse`),
    });
    expect(isDisabled(hide)).toBe(false);
    await setupUser().click(hide);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});
