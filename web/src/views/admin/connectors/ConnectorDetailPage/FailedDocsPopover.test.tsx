/** The failed documents panel over a faked `/errors` and `errors/resolve`, and the chips that open the floating panels. */
import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { Button, Popover } from "@opal/components";
import { SvgUser, SvgUsers } from "@opal/icons";
import englishMessages from "@/i18n/messages/en.json";
import type {
  IndexAttemptError,
  SyncAttemptError,
  SyncEntityKind,
} from "@/lib/connectors/types";
import type { ActivityScope } from "@/lib/connectors/ccPair/hooks";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import FailedDocsPopoverContent from "@/views/admin/connectors/ConnectorDetailPage/FailedDocsPopover";
import {
  SALES_DRIVE,
  groupSyncRun,
  holdsIcon,
  indexRun,
  installActivityFeed,
  referencePaths,
  restoreFetch,
} from "@tests/setup/activityFeedTestUtils";

const CC_PAIR_ID = SALES_DRIVE.id;
const ATTEMPT_ID = 101;
const LATER_RUN_ID = 999;

const NOW = Date.now();
const minutesAgo = (minutes: number) =>
  new Date(NOW - minutes * 60_000).toISOString();

function errorRow(
  id: number,
  minutes: number,
  fields: Partial<IndexAttemptError> & { failure_message: string }
): IndexAttemptError {
  return {
    id,
    connector_credential_pair_id: CC_PAIR_ID,
    document_id: null,
    document_link: null,
    document_name: null,
    entity_id: null,
    failed_time_range_start: null,
    failed_time_range_end: null,
    is_resolved: false,
    resolved_reason: null,
    resolved_by_index_attempt_id: null,
    resolved_at: null,
    time_created: minutesAgo(minutes),
    index_attempt_id: ATTEMPT_ID,
    error_type: null,
    ...fields,
  };
}

// Open: two documents (one titled) and one whole mailbox.
const OPEN_TITLED = errorRow(1, 1, {
  document_id: "doc-a",
  document_name: "Q3 renewal",
  document_link: "https://drive.example.com/doc-a",
  failure_message: "Timeout while fetching the renewal.",
});
const OPEN_UNTITLED = errorRow(2, 2, {
  document_id: "doc-b",
  failure_message: "Permission denied for the folder.",
});
const OPEN_ENTITY = errorRow(3, 3, {
  entity_id: "mailbox-1",
  failure_message: "Mailbox unavailable.",
});
// Resolved without retry: is_resolved stays false.
const WITHOUT_RETRY_NEW = errorRow(4, 4, {
  document_id: "doc-c",
  failure_message: "Rate limited on doc-c.",
  resolved_reason: "without_retry",
  resolved_at: minutesAgo(1),
});
const WITHOUT_RETRY_OLD = errorRow(7, 7, {
  document_id: "doc-f",
  failure_message: "Rate limited on doc-f.",
  resolved_reason: "without_retry",
  resolved_at: minutesAgo(1),
});
const LATER_RUN = errorRow(5, 5, {
  document_id: "doc-d",
  failure_message: "Parser crashed on doc-d.",
  is_resolved: true,
  resolved_reason: "later_run",
  resolved_by_index_attempt_id: LATER_RUN_ID,
  resolved_at: minutesAgo(1),
});
const RETRIED = errorRow(6, 6, {
  document_id: "doc-e",
  failure_message: "Parser crashed on doc-e.",
  is_resolved: true,
  resolved_reason: "retry",
  resolved_at: minutesAgo(1),
});
// Resolved with no reason recorded.
const LEGACY = errorRow(8, 0.5, {
  document_id: "doc-g",
  failure_message: "Legacy failure on doc-g.",
  is_resolved: true,
});

const ALL_ROWS = [
  OPEN_TITLED,
  OPEN_UNTITLED,
  OPEN_ENTITY,
  WITHOUT_RETRY_NEW,
  WITHOUT_RETRY_OLD,
  LATER_RUN,
  RETRIED,
  LEGACY,
];

const isOpen = (row: IndexAttemptError) =>
  !row.is_resolved && row.resolved_reason === null;

/** `order=state`: open, then resolved without retry, then closed. */
function stateRank(row: IndexAttemptError): number {
  if (isOpen(row)) return 0;
  return row.resolved_reason === "without_retry" ? 1 : 2;
}

interface FakeRequest {
  method: string;
  url: URL;
  body: Record<string, unknown> | null;
}

let originalFetch: typeof fetch | undefined;

/** Serves `/errors` and `errors/resolve` the way the backend does until the test ends. */
function installErrorsRoute(seed: IndexAttemptError[]) {
  const rows = seed.map((row) => ({ ...row }));
  const requests: FakeRequest[] = [];
  originalFetch = global.fetch;
  const json = (body: unknown, status = 200) =>
    ({
      ok: status < 400,
      status,
      headers: new Headers({ "content-type": "application/json" }),
      json: async () => body,
      text: async () => JSON.stringify(body),
    }) as Response;

  global.fetch = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null;
      requests.push({ method, url, body });
      const base = `/api/manage/admin/cc-pair/${CC_PAIR_ID}/errors`;

      if (method === "GET" && url.pathname === base) {
        const params = url.searchParams;
        const attempt = params.get("index_attempt_id");
        const q = (params.get("q") ?? "").toLowerCase();
        const includeResolved = params.get("include_resolved") === "true";
        const pageNum = Number(params.get("page_num") ?? "0");
        const pageSize = Number(params.get("page_size") ?? "10");
        const matching = rows
          .filter((row) => includeResolved || isOpen(row))
          .filter(
            (row) =>
              attempt === null || String(row.index_attempt_id) === attempt
          )
          .filter(
            (row) =>
              q === "" ||
              [row.failure_message, row.document_id, row.entity_id].some(
                (field) => field?.toLowerCase().includes(q)
              )
          )
          .sort(
            (a, b) =>
              (params.get("order") === "state"
                ? stateRank(a) - stateRank(b)
                : 0) ||
              Date.parse(b.time_created) - Date.parse(a.time_created) ||
              b.id - a.id
          );
        return json({
          items: matching.slice(pageNum * pageSize, (pageNum + 1) * pageSize),
          total_items: matching.length,
        });
      }
      if (method === "POST" && url.pathname === `${base}/resolve`) {
        const ids = (body?.error_ids as number[] | undefined) ?? [];
        let resolved = 0;
        rows.forEach((row) => {
          if (!ids.includes(row.id) || !isOpen(row)) return;
          row.resolved_reason = "without_retry";
          row.resolved_at = new Date().toISOString();
          resolved += 1;
        });
        return json({ resolved_count: resolved });
      }
      return json({ detail: `No fake for ${method} ${url.pathname}` }, 404);
    }
  ) as typeof fetch;

  const sent = (method: string, suffix: string) =>
    requests.filter(
      (request) =>
        request.method === method && request.url.pathname.endsWith(suffix)
    );
  return {
    posts: (suffix: string) => sent("POST", suffix),
    gets: (suffix: string) => sent("GET", suffix),
  };
}

afterEach(() => {
  if (originalFetch !== undefined) global.fetch = originalFetch;
  originalFetch = undefined;
  restoreFetch();
});

function renderPanel(
  overrides: {
    canResolve?: boolean;
    canRetryAll?: boolean;
    canResolveErrors?: boolean;
    onResolve?: jest.Mock;
  } = {}
) {
  const onResolve = overrides.onResolve ?? jest.fn();
  render(
    <Popover open>
      <Popover.Trigger asChild>
        <Button prominence="tertiary">21 docs failed</Button>
      </Popover.Trigger>
      <FailedDocsPopoverContent
        ccPairId={CC_PAIR_ID}
        attemptId={ATTEMPT_ID}
        kind="docs"
        canResolve={overrides.canResolve ?? true}
        canRetryAll={overrides.canRetryAll}
        canResolveErrors={overrides.canResolveErrors}
        onResolve={onResolve}
        resolving={false}
        placement="below"
      />
    </Popover>
  );
  return { onResolve };
}

const panel = () => screen.getByRole("dialog");

async function shownMessage(row: IndexAttemptError): Promise<HTMLElement> {
  return waitFor(() => within(panel()).getByText(row.failure_message));
}

interface ShownRow {
  id: number;
  failure_message: string;
}

/** The largest element around `row`'s message that holds no other row's message. */
function rowOf(row: ShownRow, pool: ShownRow[] = ALL_ROWS): HTMLElement {
  const root = panel();
  const message = within(root).getByText(row.failure_message);
  const others = pool
    .filter((other) => other.id !== row.id)
    .map((other) => within(root).queryByText(other.failure_message))
    .filter((element): element is HTMLElement => element !== null);
  let element: HTMLElement = message;
  while (
    element.parentElement !== null &&
    element.parentElement !== root &&
    !others.some((other) => element.parentElement!.contains(other))
  ) {
    element = element.parentElement;
  }
  return element;
}

const precedes = (a: Node, b: Node) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);

const divider = () => within(panel()).getAllByText("Resolved Errors")[0]!;

// ── AC-1: width ───────────────────────────────────────────────────────────

describe("AC-1: failed documents panel size", () => {
  it("AC-1: the panel is 640 wide", async () => {
    installErrorsRoute(ALL_ROWS);
    renderPanel();
    await shownMessage(OPEN_TITLED);

    const content = panel();
    const width = `${content.getAttribute("style") ?? ""} ${content.className}`;
    expect(width).toMatch(
      /contextual-menu-3x-large|40rem|640px|\bw-160\b|\bw-\[40rem\]|\bw-\[640px\]/
    );
  });
});

// ── AC-3: header ──────────────────────────────────────────────────────────

describe("AC-3: search and Retry All Docs", () => {
  it("AC-3: a search narrows the rows and Retry All Docs stays and retries every open failed document of the run", async () => {
    installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    const { onResolve } = renderPanel();
    await shownMessage(OPEN_TITLED);

    await user.type(within(panel()).getByRole("searchbox"), "permission");
    await waitFor(() =>
      expect(
        within(panel()).queryByText(OPEN_TITLED.failure_message)
      ).toBeNull()
    );
    expect(
      within(panel()).getByText(OPEN_UNTITLED.failure_message)
    ).toBeInTheDocument();

    await user.click(
      within(panel()).getByRole("button", { name: "Retry All Docs" })
    );
    expect(onResolve).toHaveBeenCalledTimes(1);
    const [errorIds] = onResolve.mock.calls[0] as [number[] | null];
    // Every open document of the run, not only the ones the search shows.
    if (errorIds !== null) {
      expect(errorIds).toEqual(
        expect.arrayContaining([OPEN_TITLED.id, OPEN_UNTITLED.id])
      );
      expect(errorIds).not.toContain(LATER_RUN.id);
    }
  });
});

// ── AC-4: row actions ─────────────────────────────────────────────────────

describe("AC-4: row actions", () => {
  it("AC-4: an open document row offers Resolve without Retry and Retry Doc; Retry Doc retries that document", async () => {
    installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    const { onResolve } = renderPanel();
    await shownMessage(OPEN_TITLED);
    const row = rowOf(OPEN_TITLED);
    await user.hover(row);

    expect(
      within(row).getByRole("button", { name: "Resolve without Retry" })
    ).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Retry Doc" }));

    expect(onResolve).toHaveBeenCalledWith([OPEN_TITLED.id]);
  });

  it("AC-4: Resolve without Retry posts errors/resolve with that error id and moves the row under Resolved Errors", async () => {
    const route = installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    const { onResolve } = renderPanel();
    await shownMessage(OPEN_TITLED);
    const row = rowOf(OPEN_TITLED);
    await user.hover(row);

    await user.click(
      within(row).getByRole("button", { name: "Resolve without Retry" })
    );

    const resolvePath = `/cc-pair/${CC_PAIR_ID}/errors/resolve`;
    await waitFor(() => expect(route.posts(resolvePath)).toHaveLength(1));
    expect(route.posts(resolvePath)[0]!.body).toEqual({
      error_ids: [OPEN_TITLED.id],
    });
    expect(route.posts("/targeted-reindex")).toHaveLength(0);
    expect(onResolve).not.toHaveBeenCalled();

    await waitFor(() =>
      expect(
        precedes(
          divider(),
          within(panel()).getByText(OPEN_TITLED.failure_message)
        )
      ).toBe(true)
    );
    expect(
      within(rowOf(OPEN_TITLED)).getByRole("button", {
        name: "Resolved without Retry",
      })
    ).toBeInTheDocument();
  });

  it("AC-4: an error with no document shows Resolve only, which posts errors/resolve", async () => {
    const route = installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    const { onResolve } = renderPanel();
    await shownMessage(OPEN_ENTITY);
    const row = rowOf(OPEN_ENTITY);
    await user.hover(row);

    expect(within(row).queryByRole("button", { name: "Retry Doc" })).toBeNull();
    expect(
      within(row).queryByRole("button", { name: "Resolve without Retry" })
    ).toBeNull();
    await user.click(within(row).getByRole("button", { name: "Resolve" }));

    await waitFor(() =>
      expect(
        route.posts(`/cc-pair/${CC_PAIR_ID}/errors/resolve`)[0]?.body
      ).toEqual({ error_ids: [OPEN_ENTITY.id] })
    );
    expect(onResolve).not.toHaveBeenCalled();
  });
});

describe("AC-4: what the card allows", () => {
  it("AC-4: without open documents on the run, Retry All Docs is hidden and rows keep their actions", async () => {
    installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    renderPanel({ canRetryAll: false });
    await shownMessage(OPEN_TITLED);

    expect(
      within(panel()).queryByRole("button", { name: "Retry All Docs" })
    ).toBeNull();
    const row = rowOf(OPEN_TITLED);
    await user.hover(row);
    expect(
      within(row).getByRole("button", { name: "Retry Doc" })
    ).toBeInTheDocument();
  });

  it("AC-4: a viewer who cannot resolve errors sees Retry Doc only on an open row", async () => {
    installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    renderPanel({ canResolveErrors: false });
    await shownMessage(OPEN_TITLED);
    const row = rowOf(OPEN_TITLED);
    await user.hover(row);

    expect(
      within(row).getByRole("button", { name: "Retry Doc" })
    ).toBeInTheDocument();
    expect(
      within(row).queryByRole("button", { name: "Resolve without Retry" })
    ).toBeNull();
  });
});

// ── AC-5: resolved groups ─────────────────────────────────────────────────

describe("AC-5: resolved groups", () => {
  it("AC-5: open errors, the Resolved Errors divider, resolved without retry, then resolved by a later run or a retry, newest first in each", async () => {
    installErrorsRoute(ALL_ROWS);
    renderPanel();
    await shownMessage(RETRIED);

    const message = (row: IndexAttemptError) =>
      within(panel()).getByText(row.failure_message);
    const order = [
      OPEN_TITLED,
      OPEN_UNTITLED,
      OPEN_ENTITY,
      WITHOUT_RETRY_NEW,
      WITHOUT_RETRY_OLD,
      LATER_RUN,
      RETRIED,
    ];
    for (let i = 0; i + 1 < order.length; i++) {
      expect(precedes(message(order[i]!), message(order[i + 1]!))).toBe(true);
    }
    expect(precedes(message(OPEN_ENTITY), divider())).toBe(true);
    expect(precedes(divider(), message(WITHOUT_RETRY_NEW))).toBe(true);
    // A legacy row without a reason still reads as resolved.
    expect(precedes(divider(), message(LEGACY))).toBe(true);
  });

  it("AC-5: pages in the server's state order, so the divider sits once before the first resolved row across pages", async () => {
    // 101 open rows fill page one and spill onto page two, behind newer resolved rows.
    const openRows = Array.from({ length: 101 }, (_, index) =>
      errorRow(1000 + index, 10 + index, {
        document_id: `doc-open-${index}`,
        failure_message: `Open failure ${index}.`,
      })
    );
    const lastOpen = openRows[openRows.length - 1]!;
    const resolvedRows = [WITHOUT_RETRY_NEW, LATER_RUN, LEGACY];
    const route = installErrorsRoute([...resolvedRows, ...openRows]);
    renderPanel();
    await shownMessage(openRows[0]!);

    for (const request of route.gets("/errors")) {
      expect(request.url.searchParams.get("order")).toBe("state");
    }
    // Page one holds open rows only, so nothing resolved and no divider yet.
    expect(within(panel()).queryByText("Resolved Errors")).toBeNull();
    for (const row of resolvedRows) {
      expect(within(panel()).queryByText(row.failure_message)).toBeNull();
    }

    const user = userEvent.setup();
    await user.click(
      within(panel()).getByRole("button", { name: "Show more" })
    );
    await shownMessage(LEGACY);

    expect(within(panel()).getAllByText("Resolved Errors")).toHaveLength(1);
    const message = (row: IndexAttemptError) =>
      within(panel()).getByText(row.failure_message);
    // The server's order: open newest first, without retry, then closed newest first.
    const order = [...openRows, WITHOUT_RETRY_NEW, LEGACY, LATER_RUN];
    for (let i = 0; i + 1 < order.length; i++) {
      expect(precedes(message(order[i]!), message(order[i + 1]!))).toBe(true);
    }
    expect(precedes(message(lastOpen), divider())).toBe(true);
    expect(precedes(divider(), message(WITHOUT_RETRY_NEW))).toBe(true);
  });

  it("AC-5: a row resolved without retry shows Resolved without Retry and still offers Retry Doc", async () => {
    installErrorsRoute(ALL_ROWS);
    const user = userEvent.setup();
    const { onResolve } = renderPanel();
    await shownMessage(WITHOUT_RETRY_NEW);
    const row = rowOf(WITHOUT_RETRY_NEW);
    await user.hover(row);

    expect(
      within(row).getByRole("button", { name: "Resolved without Retry" })
    ).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Retry Doc" }));
    expect(onResolve).toHaveBeenCalledWith([WITHOUT_RETRY_NEW.id]);
  });

  it("AC-5: a row resolved by a later run links to that run on the Indexing tab; a legacy row has no link", async () => {
    installErrorsRoute(ALL_ROWS);
    renderPanel();
    await shownMessage(LATER_RUN);

    const link = within(rowOf(LATER_RUN)).getByRole("link", {
      name: "Resolved by Later Run",
    });
    const href = link.getAttribute("href") ?? "";
    expect(href).toMatch(new RegExp(`/admin/connector/${CC_PAIR_ID}(?![0-9])`));
    expect(href).toMatch(/tab=indexing/);
    expect(href).toMatch(new RegExp(`[=/]${LATER_RUN_ID}(?![0-9])`));

    const legacy = rowOf(LEGACY);
    expect(
      within(legacy).queryByRole("link", { name: "Resolved by Later Run" })
    ).toBeNull();
    expect(
      within(legacy).queryByRole("button", { name: "Resolved by Later Run" })
    ).toBeNull();
  });
});

// ── AC-6: identity ────────────────────────────────────────────────────────

describe("AC-6: row identity", () => {
  it("AC-6: a titled document reads '{title} ({id})' with an open-document link; an untitled one shows its id only", async () => {
    installErrorsRoute(ALL_ROWS);
    renderPanel();
    await shownMessage(OPEN_TITLED);

    const titled = rowOf(OPEN_TITLED);
    expect(titled.textContent).toContain("Q3 renewal (doc-a)");
    expect(
      within(titled).getByRole("link", { name: "Open the document" })
    ).toHaveAttribute("href", OPEN_TITLED.document_link);

    const untitled = rowOf(OPEN_UNTITLED);
    expect(untitled.textContent).toContain("doc-b");
    expect(untitled.textContent).not.toContain("(doc-b)");
  });
});

// ── AC-1: chips stay selected ─────────────────────────────────────────────

describe("AC-1: the chip that opened a panel shows selected", () => {
  const PAIR: ActivityScope = {
    ccPairId: SALES_DRIVE.id,
    canResolve: true,
    canResolveRuns: true,
  };
  const FAILED = indexRun({
    id: ATTEMPT_ID,
    status: "failed",
    minutesAgo: 4,
    errorMsg: "Service unavailable.",
    trace: "Traceback: service unavailable",
    errorCount: 21,
    openErrors: 5,
  });

  beforeEach(() => {
    Element.prototype.scrollIntoView = jest.fn();
    window.sessionStorage.clear();
  });

  it("AC-1: the docs failed chip and the Stack Trace chip are aria-pressed while their panel is open", async () => {
    installActivityFeed([FAILED]);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    const docsChip = await screen.findByRole("button", {
      name: /\d+ docs? failed/,
    });
    expect(docsChip).not.toHaveAttribute("aria-pressed", "true");
    await user.click(docsChip);
    await screen.findByRole("dialog");
    expect(docsChip).toHaveAttribute("aria-pressed", "true");

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(docsChip).not.toHaveAttribute("aria-pressed", "true");

    const traceChip = screen.getByRole("button", {
      name: englishMessages.admin.connector.activity.tags.stackTrace,
    });
    await user.click(traceChip);
    await screen.findByRole("dialog");
    expect(traceChip).toHaveAttribute("aria-pressed", "true");
  });
});

// ── AC-2: the stack trace follows the content width while open ────────────

describe("AC-2: a stack trace opened below moves beside on a resize", () => {
  const PAIR: ActivityScope = {
    ccPairId: SALES_DRIVE.id,
    canResolve: true,
    canResolveRuns: true,
  };
  const FAILED = indexRun({
    id: ATTEMPT_ID,
    status: "failed",
    minutesAgo: 4,
    errorMsg: "Service unavailable.",
    trace: "Traceback: service unavailable",
  });
  const originalObserver = global.ResizeObserver;
  const originalWidth = window.innerWidth;
  const observers = new Set<() => void>();

  beforeEach(() => {
    Element.prototype.scrollIntoView = jest.fn();
    window.sessionStorage.clear();
    global.ResizeObserver = class {
      constructor(callback: ResizeObserverCallback) {
        observers.add(() => callback([], this as unknown as ResizeObserver));
      }
      observe() {}
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver;
  });

  afterEach(() => {
    global.ResizeObserver = originalObserver;
    window.innerWidth = originalWidth;
    observers.clear();
  });

  it("AC-2: widening past 1024 while the trace is open measures its anchor at the side panel's edge", async () => {
    window.innerWidth = 800;
    installActivityFeed([FAILED]);
    const user = userEvent.setup();
    const { container } = render(
      <ActivityPanel scope={PAIR} title="Activities" />
    );
    const traceChip = await screen.findByRole("button", {
      name: englishMessages.admin.connector.activity.tags.stackTrace,
    });
    await user.click(traceChip);
    await screen.findByRole("dialog");

    const sidePanel =
      container.querySelector<HTMLElement>("[data-side-panel]")!;
    jest
      .spyOn(sidePanel, "getBoundingClientRect")
      .mockReturnValue(new DOMRect(600, 0, 400, 900));
    window.innerWidth = 1280;
    act(() => observers.forEach((notify) => notify()));

    // The beside anchor is a zero-width line at the side panel's left edge.
    await waitFor(() => {
      const line = Array.from(
        container.querySelectorAll<HTMLElement>("span[aria-hidden]")
      ).find((span) => span.style.width === "0px");
      expect(line?.style.left).toBe("600px");
    });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("AC-2: a card that grows while the trace is open beside moves the anchor to the chip's new line", async () => {
    window.innerWidth = 1280;
    installActivityFeed([FAILED]);
    const user = userEvent.setup();
    const { container } = render(
      <ActivityPanel scope={PAIR} title="Activities" />
    );
    const traceChip = await screen.findByRole("button", {
      name: englishMessages.admin.connector.activity.tags.stackTrace,
    });
    // The chip's text line, wherever the card renders it.
    let chipTop = 100;
    const measureChip = (chip: HTMLElement) =>
      jest
        .spyOn(
          chip.querySelector<HTMLElement>("[data-opal-content-title]") ?? chip,
          "getBoundingClientRect"
        )
        .mockImplementation(() => new DOMRect(40, chipTop, 80, 16));
    measureChip(traceChip);
    await user.click(traceChip);
    await screen.findByRole("dialog");
    const anchorTop = () =>
      Array.from(
        container.querySelectorAll<HTMLElement>("span[aria-hidden]")
      ).find((span) => span.style.width === "0px")?.style.top;
    await waitFor(() => expect(anchorTop()).toBe("100px"));

    // A longer message wraps and pushes the chip down the card.
    chipTop = 140;
    measureChip(
      screen.getByRole("button", {
        name: englishMessages.admin.connector.activity.tags.stackTrace,
      })
    );
    act(() => observers.forEach((notify) => notify()));

    await waitFor(() => expect(anchorTop()).toBe("140px"));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

// ── AC-5: the list once nothing is open ───────────────────────────────────

describe("AC-5: the list once its last open error is resolved", () => {
  const PAIR: ActivityScope = {
    ccPairId: SALES_DRIVE.id,
    canResolve: true,
    canResolveRuns: true,
  };

  beforeEach(() => {
    Element.prototype.scrollIntoView = jest.fn();
    window.sessionStorage.clear();
  });

  // A failed run stays under Failures; a run that completed with errors leaves the open feed with its last open error.
  it.each(["failed", "completed_with_errors"] as const)(
    "AC-5: resolving the only open error of a %s run keeps the panel open with the row under Resolved Errors",
    async (status) => {
      const RUN = indexRun({
        id: ATTEMPT_ID,
        status,
        minutesAgo: 4,
        errorMsg: status === "failed" ? "Service unavailable." : null,
        openErrors: 1,
      });
      const feed = installActivityFeed([RUN]);
      const feedFetch = global.fetch;
      const route = installErrorsRoute([OPEN_UNTITLED]);
      const errorsFetch = global.fetch;
      // One backend: the resolve also clears the run's open counts in the feed.
      global.fetch = jest.fn(
        async (input: RequestInfo | URL, init?: RequestInit) => {
          const path = new URL(String(input), "http://localhost").pathname;
          if (!path.includes("/errors")) return feedFetch(input, init);
          const response = await errorsFetch(input, init);
          if (path.endsWith("/errors/resolve") && RUN.run.kind === "indexing") {
            RUN.errors = "closed";
            RUN.run.attempt.open_error_count = 0;
            RUN.run.attempt.open_doc_error_count = 0;
          }
          return response;
        }
      ) as typeof fetch;
      const user = userEvent.setup();
      render(<ActivityPanel scope={PAIR} title="Activities" />);

      await user.click(
        await screen.findByRole("button", { name: /\d+ docs? failed/ })
      );
      await shownMessage(OPEN_UNTITLED);
      const row = rowOf(OPEN_UNTITLED);
      await user.hover(row);
      const feedReads = feed.calls("GET", "/runs").length;
      await user.click(
        within(row).getByRole("button", { name: "Resolve without Retry" })
      );

      await waitFor(() =>
        expect(
          route.posts(`/cc-pair/${CC_PAIR_ID}/errors/resolve`)
        ).toHaveLength(1)
      );
      // The feed has reread the run with no open errors.
      await waitFor(() =>
        expect(feed.calls("GET", "/runs").length).toBeGreaterThan(feedReads)
      );
      await waitFor(() =>
        expect(
          precedes(
            divider(),
            within(panel()).getByText(OPEN_UNTITLED.failure_message)
          )
        ).toBe(true)
      );
      // With nothing open the chip cannot tell documents from sources, so it counts items.
      expect(
        screen.getByRole("button", { name: /\d+ items? failed/ })
      ).toHaveAttribute("aria-pressed", "true");

      // Nothing of the run is open, so the bulk retry leaves.
      await waitFor(() =>
        expect(
          within(panel()).queryByRole("button", { name: "Retry All Docs" })
        ).toBeNull()
      );

      // Closing the panel lets the next read drop a run with nothing open.
      await user.keyboard("{Escape}");
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      await waitFor(() =>
        expect(
          screen.queryByRole("button", { name: /\d+ items? failed/ }) === null
        ).toBe(status !== "failed")
      );
    }
  );
  it("AC-5: with Resolved shown, a run whose last open error resolves keeps its open card and panel", async () => {
    const RUN = indexRun({
      id: ATTEMPT_ID,
      status: "completed_with_errors",
      minutesAgo: 4,
      openErrors: 1,
    });
    const feed = installActivityFeed([RUN]);
    const feedFetch = global.fetch;
    const route = installErrorsRoute([OPEN_UNTITLED]);
    const errorsFetch = global.fetch;
    // The resolve closes the run, so the next read lists it under Resolved.
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), "http://localhost").pathname;
        if (!path.includes("/errors")) return feedFetch(input, init);
        const response = await errorsFetch(input, init);
        if (path.endsWith("/errors/resolve") && RUN.run.kind === "indexing") {
          RUN.errors = "closed";
          RUN.run.attempt.open_error_count = 0;
          RUN.run.attempt.open_doc_error_count = 0;
        }
        return response;
      }
    ) as typeof fetch;
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);
    await user.click(
      await screen.findByRole("button", { name: /^(Show Filters|Filters)$/ })
    );
    await user.click(await screen.findByRole("button", { name: /^Resolved$/ }));

    await user.click(
      await screen.findByRole("button", { name: /\d+ docs? failed/ })
    );
    await shownMessage(OPEN_UNTITLED);
    const row = rowOf(OPEN_UNTITLED);
    await user.hover(row);
    const feedReads = feed.calls("GET", "/runs").length;
    await user.click(
      within(row).getByRole("button", { name: "Resolve without Retry" })
    );
    await waitFor(() =>
      expect(route.posts(`/cc-pair/${CC_PAIR_ID}/errors/resolve`)).toHaveLength(
        1
      )
    );
    await waitFor(() =>
      expect(feed.calls("GET", "/runs").length).toBeGreaterThan(feedReads)
    );

    await waitFor(() =>
      expect(
        precedes(
          divider(),
          within(panel()).getByText(OPEN_UNTITLED.failure_message)
        )
      ).toBe(true)
    );
    const chips = screen.getAllByRole("button", { name: /\d+ items? failed/ });
    expect(chips).toHaveLength(1);
    expect(chips[0]).toHaveAttribute("aria-pressed", "true");
  });
  it("AC-5: a running run that fails while its panel is open keeps one card and Retry All Docs", async () => {
    const RUN = indexRun({
      id: ATTEMPT_ID,
      status: "in_progress",
      minutesAgo: 4,
      openErrors: 2,
    });
    const feed = installActivityFeed([RUN]);
    const feedFetch = global.fetch;
    const route = installErrorsRoute([OPEN_TITLED, OPEN_UNTITLED]);
    const errorsFetch = global.fetch;
    // The run fails between reads, so the next read lists it under Failures with one document still open.
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), "http://localhost").pathname;
        if (!path.includes("/errors")) return feedFetch(input, init);
        const response = await errorsFetch(input, init);
        if (path.endsWith("/errors/resolve") && RUN.run.kind === "indexing") {
          RUN.group = "failed";
          RUN.run.attempt.status = "failed";
          RUN.run.attempt.open_error_count = 1;
          RUN.run.attempt.open_doc_error_count = 1;
        }
        return response;
      }
    ) as typeof fetch;
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: /\d+ docs? failed/ })
    );
    await shownMessage(OPEN_UNTITLED);
    const row = rowOf(OPEN_UNTITLED);
    await user.hover(row);
    const feedReads = feed.calls("GET", "/runs").length;
    await user.click(
      within(row).getByRole("button", { name: "Resolve without Retry" })
    );
    await waitFor(() =>
      expect(route.posts(`/cc-pair/${CC_PAIR_ID}/errors/resolve`)).toHaveLength(
        1
      )
    );

    await waitFor(() =>
      expect(feed.calls("GET", "/runs").length).toBeGreaterThan(feedReads)
    );
    expect(
      screen.getAllByRole("button", { name: /\d+ docs? failed/ })
    ).toHaveLength(1);
    expect(
      within(panel()).getByRole("button", { name: "Retry All Docs" })
    ).toBeInTheDocument();
  });
  it("AC-5: a run that newer failures push past the loaded page keeps its open counts and Retry All Docs", async () => {
    // The open card is the last of a full first page of failures.
    const RUN = indexRun({
      id: ATTEMPT_ID,
      status: "failed",
      minutesAgo: 60,
      errorMsg: "Service unavailable.",
      openErrors: 2,
    });
    const older = Array.from({ length: 19 }, (_, index) =>
      indexRun({
        id: 500 + index,
        status: "failed",
        minutesAgo: 10 + index,
        errorMsg: `Outage ${index}.`,
      })
    );
    const NEWEST = indexRun({
      id: 600,
      status: "success",
      minutesAgo: 1,
    });
    const feed = installActivityFeed([NEWEST, ...older, RUN]);
    const feedFetch = global.fetch;
    const route = installErrorsRoute([OPEN_TITLED, OPEN_UNTITLED]);
    const errorsFetch = global.fetch;
    // A newer run fails between reads, so the next read lists the open card on page two with one document still open.
    global.fetch = jest.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = new URL(String(input), "http://localhost").pathname;
        if (!path.includes("/errors")) return feedFetch(input, init);
        const response = await errorsFetch(input, init);
        if (
          path.endsWith("/errors/resolve") &&
          RUN.run.kind === "indexing" &&
          NEWEST.run.kind === "indexing"
        ) {
          NEWEST.group = RUN.group;
          NEWEST.run.attempt.status = "failed";
          RUN.run.attempt.open_error_count = 1;
          RUN.run.attempt.open_doc_error_count = 1;
        }
        return response;
      }
    ) as typeof fetch;
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: /\d+ docs? failed/ })
    );
    await shownMessage(OPEN_UNTITLED);
    const row = rowOf(OPEN_UNTITLED);
    await user.hover(row);
    const feedReads = feed.calls("GET", "/runs").length;
    await user.click(
      within(row).getByRole("button", { name: "Resolve without Retry" })
    );
    await waitFor(() =>
      expect(route.posts(`/cc-pair/${CC_PAIR_ID}/errors/resolve`)).toHaveLength(
        1
      )
    );
    await waitFor(() =>
      expect(feed.calls("GET", "/runs").length).toBeGreaterThan(feedReads)
    );
    await waitFor(() =>
      expect(
        screen.getByText(englishMessages.admin.connector.activity.more)
      ).toBeInTheDocument()
    );

    expect(
      screen.getByRole("button", { name: /\d+ docs? failed/ })
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      within(panel()).getByRole("button", { name: "Retry All Docs" })
    ).toBeInTheDocument();
  });
});

// ── Failed users and groups ───────────────────────────────────────────────

const SYNC_ATTEMPT_ID = 702;

function syncErrorRow(
  id: number,
  minutes: number,
  entityKind: SyncEntityKind,
  fields: Pick<SyncAttemptError, "entity_id" | "failure_message">
): SyncAttemptError {
  return {
    id,
    connector_credential_pair_id: CC_PAIR_ID,
    external_group_sync_attempt_id: SYNC_ATTEMPT_ID,
    entity_kind: entityKind,
    entity_name: null,
    time_created: minutesAgo(minutes),
    is_resolved: false,
    resolved_reason: null,
    resolved_at: null,
    ...fields,
  };
}

const FAILED_BOB = syncErrorRow(11, 1, "user", {
  entity_id: "acct-bob",
  failure_message: "memberOf page 2 returned 500.",
});
const FAILED_ANN = syncErrorRow(12, 2, "user", {
  entity_id: "acct-ann",
  failure_message: "User lookup timed out.",
});
const FAILED_SALES = syncErrorRow(13, 3, "group", {
  entity_id: "grp-sales",
  failure_message: "Group members page returned 403.",
});
const SYNC_ROWS = [FAILED_BOB, FAILED_ANN, FAILED_SALES];

const isOpenSync = (row: SyncAttemptError) =>
  !row.is_resolved && row.resolved_reason === null;

/** Serves `/sync-errors` and `sync-errors/resolve` over the feed fake, as the backend does. A run resolve closes the run's open rows without retry. */
function installSyncErrorsRoute(seed: SyncAttemptError[]) {
  const rows = seed.map((row) => ({ ...row }));
  const resolvePosts: number[][] = [];
  const listReads: URLSearchParams[] = [];
  const feedFetch = global.fetch;
  const base = `/api/manage/admin/cc-pair/${CC_PAIR_ID}/sync-errors`;
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  const closeWithoutRetry = (row: SyncAttemptError) => {
    row.resolved_reason = "without_retry";
    row.resolved_at = new Date().toISOString();
  };
  global.fetch = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      if (method === "GET" && url.pathname === base) {
        const params = url.searchParams;
        listReads.push(params);
        const attempt = params.get("attempt_id");
        const kind = params.get("entity_kind");
        const q = (params.get("q") ?? "").toLowerCase();
        const includeResolved = params.get("include_resolved") === "true";
        const pageNum = Number(params.get("page_num") ?? "0");
        const pageSize = Number(params.get("page_size") ?? "10");
        const matching = rows
          .filter((row) => includeResolved || isOpenSync(row))
          .filter(
            (row) =>
              attempt === null ||
              String(row.external_group_sync_attempt_id) === attempt
          )
          .filter((row) => kind === null || row.entity_kind === kind)
          .filter(
            (row) =>
              q === "" ||
              [row.failure_message, row.entity_id, row.entity_name].some(
                (field) => field?.toLowerCase().includes(q)
              )
          )
          .sort(
            (a, b) =>
              (params.get("order") === "state"
                ? Number(!isOpenSync(a)) - Number(!isOpenSync(b))
                : 0) ||
              Date.parse(b.time_created) - Date.parse(a.time_created) ||
              b.id - a.id
          );
        return json({
          items: matching.slice(pageNum * pageSize, (pageNum + 1) * pageSize),
          total_items: matching.length,
        });
      }
      if (method === "POST" && url.pathname === `${base}/resolve`) {
        const ids = (JSON.parse(String(init?.body)) as { error_ids: number[] })
          .error_ids;
        resolvePosts.push(ids);
        rows.filter((row) => ids.includes(row.id)).forEach(closeWithoutRetry);
        return json({ resolved_count: ids.length });
      }
      if (method === "POST" && url.pathname.endsWith("/runs/resolve")) {
        rows.filter(isOpenSync).forEach(closeWithoutRetry);
      }
      return feedFetch(input, init);
    }
  ) as typeof fetch;
  return { resolvePosts, listReads };
}

describe("Failed users and groups", () => {
  const PAIR: ActivityScope = {
    ccPairId: CC_PAIR_ID,
    canResolve: true,
    canResolveRuns: true,
  };
  const syncRun = () =>
    groupSyncRun({
      id: SYNC_ATTEMPT_ID,
      status: "completed_with_errors",
      minutesAgo: 4,
      failedUsers: 2,
      failedGroups: 1,
      openErrors: 3,
    });

  beforeEach(() => {
    Element.prototype.scrollIntoView = jest.fn();
    window.sessionStorage.clear();
  });

  it("the users chip lists the run's failed users with the user icon and Resolve only, no Retry", async () => {
    installActivityFeed([syncRun()]);
    const route = installSyncErrorsRoute(SYNC_ROWS);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "2 users failed to sync" })
    );
    await waitFor(() => within(panel()).getByText(FAILED_BOB.failure_message));
    expect(panel()).toHaveAccessibleName("Failed users");
    expect(
      within(panel()).getByText(FAILED_ANN.failure_message)
    ).toBeInTheDocument();
    expect(
      within(panel()).queryByText(FAILED_SALES.failure_message)
    ).toBeNull();
    // The server narrows to the chip's kind and orders by state, as /errors does.
    for (const params of route.listReads) {
      expect(params.get("entity_kind")).toBe("user");
      expect(params.get("order")).toBe("state");
    }
    expect(
      within(panel()).getByPlaceholderText("Search users\u2026")
    ).toBeInTheDocument();
    expect(
      within(panel()).queryByRole("button", { name: "Retry All Docs" })
    ).toBeNull();

    const row = rowOf(FAILED_BOB, SYNC_ROWS);
    await user.hover(row);
    expect(holdsIcon(row, referencePaths(SvgUser))).toBe(true);
    expect(within(row).getByText("acct-bob")).toBeInTheDocument();
    expect(
      within(row).getByRole("button", { name: "Resolve" })
    ).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Retry Doc" })).toBeNull();
    expect(
      within(row).queryByRole("button", { name: "Resolve without Retry" })
    ).toBeNull();
  });

  it("Resolve posts sync-errors/resolve, moves the row under Resolved Errors, and the chip keeps its count", async () => {
    installActivityFeed([syncRun()]);
    const route = installSyncErrorsRoute(SYNC_ROWS);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "2 users failed to sync" })
    );
    await waitFor(() => within(panel()).getByText(FAILED_BOB.failure_message));
    const row = rowOf(FAILED_BOB, SYNC_ROWS);
    await user.hover(row);
    await user.click(within(row).getByRole("button", { name: "Resolve" }));

    await waitFor(() => expect(route.resolvePosts).toEqual([[FAILED_BOB.id]]));
    await waitFor(() =>
      expect(
        precedes(
          divider(),
          within(panel()).getByText(FAILED_BOB.failure_message)
        )
      ).toBe(true)
    );
    // A user or group never retries, so its closed row reads Resolved.
    const resolved = rowOf(FAILED_BOB, SYNC_ROWS);
    expect(
      within(resolved).getByRole("button", { name: "Resolved" })
    ).toBeInTheDocument();
    expect(
      precedes(within(panel()).getByText(FAILED_ANN.failure_message), divider())
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "2 users failed to sync" })
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("pages a long users list from the server and searches it there", async () => {
    // 101 open users fill page one and spill onto page two, ahead of an older resolved one.
    const users = Array.from({ length: 101 }, (_, index) =>
      syncErrorRow(100 + index, 10 + index, "user", {
        entity_id: `acct-${index}`,
        failure_message: `User ${index} lookup failed.`,
      })
    );
    const lastUser = users[users.length - 1]!;
    const resolvedAnn = {
      ...FAILED_ANN,
      time_created: minutesAgo(500),
      resolved_reason: "without_retry" as const,
      resolved_at: minutesAgo(400),
    };
    installActivityFeed([
      groupSyncRun({
        id: SYNC_ATTEMPT_ID,
        status: "completed_with_errors",
        minutesAgo: 4,
        failedUsers: 102,
        failedGroups: 0,
        openErrors: 101,
      }),
    ]);
    const route = installSyncErrorsRoute([resolvedAnn, ...users]);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "102 users failed to sync" })
    );
    await waitFor(() => within(panel()).getByText(users[0]!.failure_message));
    expect(within(panel()).queryByText(lastUser.failure_message)).toBeNull();
    expect(within(panel()).queryByText("Resolved Errors")).toBeNull();

    await user.click(
      within(panel()).getByRole("button", { name: "Show more" })
    );
    await waitFor(() => within(panel()).getByText(resolvedAnn.failure_message));
    expect(route.listReads.at(-1)?.get("page_num")).toBe("1");
    expect(within(panel()).getAllByText("Resolved Errors")).toHaveLength(1);
    expect(
      precedes(within(panel()).getByText(lastUser.failure_message), divider())
    ).toBe(true);

    await user.type(within(panel()).getByRole("searchbox"), "acct-100");
    await waitFor(() =>
      expect(within(panel()).queryByText(users[0]!.failure_message)).toBeNull()
    );
    expect(route.listReads.at(-1)?.get("q")).toBe("acct-100");
    expect(
      within(panel()).getByText(lastUser.failure_message)
    ).toBeInTheDocument();
  });

  it("the groups chip lists the failed groups with the group icon", async () => {
    installActivityFeed([syncRun()]);
    const route = installSyncErrorsRoute(SYNC_ROWS);
    const user = userEvent.setup();
    render(<ActivityPanel scope={PAIR} title="Activities" />);

    await user.click(
      await screen.findByRole("button", { name: "1 group failed to sync" })
    );
    await waitFor(() =>
      within(panel()).getByText(FAILED_SALES.failure_message)
    );
    expect(panel()).toHaveAccessibleName("Failed groups");
    expect(within(panel()).queryByText(FAILED_BOB.failure_message)).toBeNull();
    expect(route.listReads.at(-1)?.get("entity_kind")).toBe("group");
    const row = rowOf(FAILED_SALES, SYNC_ROWS);
    expect(holdsIcon(row, referencePaths(SvgUsers))).toBe(true);
    expect(
      within(row).getByRole("button", { name: "Resolve" })
    ).toBeInTheDocument();
  });
});
