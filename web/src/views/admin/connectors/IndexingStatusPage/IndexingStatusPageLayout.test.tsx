/** The status page's header, counts and graph cards, fleet Activities panel, its hidden state, the row lift on activity hover and the 816 px container stacking. jsdom has no layout, so widths are pinned by class and the query each class answers to. */
import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { SvgPanelRight, SvgPlus } from "@opal/icons";
import ar from "@/i18n/messages/ar.json";
import de from "@/i18n/messages/de.json";
import en from "@/i18n/messages/en.json";
import es from "@/i18n/messages/es.json";
import fr from "@/i18n/messages/fr.json";
import ja from "@/i18n/messages/ja.json";
import ko from "@/i18n/messages/ko.json";
import pt from "@/i18n/messages/pt.json";
import zh from "@/i18n/messages/zh.json";
import {
  ConnectorCredentialPairStatus,
  type IndexingConnectorRow,
  type IndexingOverviewResponse,
} from "@/lib/connectors/types";
import type {
  SliceRange,
  ThroughputBarsProps,
  ThroughputChartViewProps,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";
import IndexingStatusPage from "@/views/admin/connectors/IndexingStatusPage";
import {
  SALES_DRIVE,
  SUPPORT_INBOX,
  cardFor,
  holdsIcon,
  indexRun,
  installActivityFeed,
  referencePaths,
  restoreFetch,
  type ActivityFeed,
  type FeedRun,
} from "@tests/setup/activityFeedTestUtils";
import {
  installChartLayout,
  resetChartLayout,
  throughputFixture,
} from "@tests/setup/throughputChartTestUtils";

// A global connector manager, who is offered Add Connector.
jest.mock("@/lib/permissions/hooks", () => ({
  ...jest.requireActual("@/lib/permissions/hooks"),
  usePermissionAuthority: () => ({
    isGlobalHolder: true,
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

const SPAN: SliceRange = {
  since: "2026-11-02T10:00:00.000Z",
  until: "2026-11-02T11:00:00.000Z",
};

// A button beside the real chart stands in for a drag across the bars, whichever chart export the page renders.
jest.mock(
  "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart",
  () => {
    const actual = jest.requireActual(
      "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart"
    );
    const { Button } = jest.requireActual("@opal/components");
    return {
      ...actual,
      __esModule: true,
      ThroughputBars: (props: ThroughputBarsProps) => (
        <>
          <actual.ThroughputBars {...props} />
          <Button onClick={() => props.onRangeSelect?.(SPAN)}>pick span</Button>
        </>
      ),
      ThroughputChartView: (props: ThroughputChartViewProps) => (
        <>
          <actual.ThroughputChartView {...props} />
          <Button onClick={() => props.onRangeSelect?.(SPAN)}>pick span</Button>
        </>
      ),
    };
  }
);

const OVERVIEW_PATH = "/api/manage/admin/index-monitoring/overview";
const CONNECTORS_PATH = "/api/manage/admin/index-monitoring/connectors";

/** The overview with `paused_connectors`. */
function overview(
  withPaused = true
): IndexingOverviewResponse & { paused_connectors?: number } {
  return {
    indexing_connectors: 3,
    active_connectors: 16,
    total_docs_indexed: 214316,
    recent_docs_indexed: 1842,
    ...(withPaused ? { paused_connectors: 2 } : {}),
    throughput: throughputFixture({ docs: { 3: 40 } }),
  };
}

const NOW = new Date().toISOString();

/** A pair's row whose latest index attempt is `attemptId`. */
function row(
  pair: typeof SALES_DRIVE,
  attemptId: number,
  failed: boolean
): IndexingConnectorRow {
  return {
    cc_pair_id: pair.id,
    name: pair.name,
    source: pair.source,
    access_type: "public",
    cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
    status: failed ? "failed" : "indexed",
    creator_email: null,
    creator_name: null,
    docs_indexed: 125,
    last_success: NOW,
    latest_index_attempt: {
      id: attemptId,
      status: failed ? "failed" : "success",
      from_beginning: false,
      new_docs_indexed: 125,
      docs_removed_from_index: 0,
      total_docs_indexed: 125,
      error_msg: failed ? "Connector failed" : null,
      error_count: 0,
      open_error_count: 0,
      open_doc_error_count: 0,
      full_exception_trace: null,
      time_started: NOW,
      time_updated: NOW,
      time_finished: NOW,
      is_new_model: false,
      is_backfill: false,
    },
    open_error_count: 0,
    queue_position: null,
    permissions: { operate: true },
  } as IndexingConnectorRow;
}

// Sales Drive's latest run failed, so the fleet's Errors level has an item and the panel opens by default.
const FAILED_RUN = indexRun({
  id: 41,
  status: "failed",
  minutesAgo: 5,
  errorMsg: "Connector failed",
  ccPairId: SALES_DRIVE.id,
});
const CLEAN_RUN = indexRun({
  id: 52,
  status: "success",
  minutesAgo: 9,
  ccPairId: SUPPORT_INBOX.id,
});
const ROWS = [row(SALES_DRIVE, 41, true), row(SUPPORT_INBOX, 52, false)];

function json(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

/** The fleet feed over `pool`, plus the overview and the connector list. */
function stubApi(pool: FeedRun[], withPaused = true): ActivityFeed {
  const feed = installActivityFeed(pool, [SALES_DRIVE, SUPPORT_INBOX]);
  const served = global.fetch;
  global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const raw =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.toString()
          : input.url;
    const path = new URL(raw, "http://localhost").pathname;
    if (path === OVERVIEW_PATH) {
      return Promise.resolve(json(overview(withPaused)));
    }
    if (path === CONNECTORS_PATH) {
      return Promise.resolve(
        json({
          items: ROWS,
          total_items: ROWS.length,
          status_counts: { failed: 1, indexed: 1 },
          source_counts: {},
          federated_connectors: [],
        })
      );
    }
    return served(input, init);
  }) as typeof fetch;
  return feed;
}

beforeEach(() => {
  installChartLayout(600);
  window.sessionStorage.clear();
  Element.prototype.scrollIntoView = jest.fn();
});

afterEach(() => {
  resetChartLayout();
  restoreFetch();
});

async function renderPage(pool: FeedRun[] = [FAILED_RUN], withPaused = true) {
  const feed = stubApi(pool, withPaused);
  render(<IndexingStatusPage />);
  // The list and the overview's figures.
  await screen.findByTestId(`indexing-connector-${SALES_DRIVE.id}`);
  await screen.findByText("214,316");
  return feed;
}

/** Waits until the default-visibility count has been asked for, so a hidden panel is settled, not loading. */
async function settled(feed: ActivityFeed) {
  await waitFor(() =>
    expect(feed.calls("GET", "/index-monitoring/runs").length).toBeGreaterThan(
      0
    )
  );
  await act(async () => {});
}

function classes(element: Element): string[] {
  return Array.from(element.classList);
}

const AT_816 = String.raw`51rem`;

/** The container-query classes on `element` for `variant` (min or max) at 816 px and `utility`, with the container name they ask for. */
function queryClasses(
  element: Element,
  variant: "min" | "max",
  utility: string
): (string | null)[] {
  const re = new RegExp(
    String.raw`^@${variant}-\[${AT_816}\](?:/([\w-]+))?:${utility}$`
  );
  return classes(element).flatMap((name) => {
    const match = re.exec(name);
    return match === null ? [] : [match[1] ?? null];
  });
}

/** The container a query on `element` measures: the nearest ancestor that is one, or the nearest with `name`. */
function queriedContainer(
  element: Element,
  name: string | null
): HTMLElement | null {
  for (let node = element.parentElement; node; node = node.parentElement) {
    const declared = classes(node).some((value) =>
      name === null
        ? value === "@container" || value.startsWith("@container/")
        : value === `@container/${name}`
    );
    if (declared) return node;
  }
  return null;
}

/** The body row that puts the panel beside the column: the element stacking at 816 px of content. */
function bodyRow(): HTMLElement {
  let node: HTMLElement | null = screen.getByText("Active connectors");
  while (node && queryClasses(node, "max", "flex-col").length === 0) {
    node = node.parentElement;
  }
  if (node === null) throw new Error("no row stacks at 816 px of content");
  return node;
}

/** `element` answers its 816 px query on the body's container, which holds the whole row. */
function expectQueriesBody(
  element: Element,
  variant: "min" | "max",
  utility: string
) {
  const names = queryClasses(element, variant, utility);
  expect(names).toHaveLength(1);
  const container = queriedContainer(element, names[0]!);
  expect(container).not.toBeNull();
  expect(container).toContainElement(bodyRow());
}

/** The child of the body row holding the counts card. */
function column(): HTMLElement {
  const rowElement = bodyRow();
  let node: HTMLElement = screen.getByText("Active connectors");
  while (node.parentElement !== rowElement) node = node.parentElement!;
  return node;
}

function panel(): HTMLElement | null {
  return screen.queryByTestId("connector-activity");
}

/** A line's parts: A and B on its root, C and D in its third column. */
function lineOf(label: string) {
  let node: HTMLElement | null = screen.getByText(label);
  let third: HTMLElement | null = null;
  while (node && third === null) {
    third = node.querySelector<HTMLElement>(":scope .basis-1\\/3");
    node = node.parentElement;
  }
  if (third === null) throw new Error(`${label} sits on no line`);
  const root = third.parentElement!;
  function part(element: HTMLElement): HTMLElement {
    let current = element;
    while (current.parentElement !== root && current.parentElement !== third) {
      if (current.parentElement === null) {
        throw new Error("element sits outside the line");
      }
      current = current.parentElement;
    }
    return current;
  }
  return { root, third, part };
}

/** Whether the button reads as selected, however Opal marks it. */
function isSelected(button: HTMLElement): boolean {
  return [button, ...Array.from(button.querySelectorAll("*"))].some(
    (node) =>
      node.getAttribute("aria-pressed") === "true" ||
      node.getAttribute("data-interactive-state") === "selected" ||
      node.getAttribute("data-interaction") === "active"
  );
}

describe("page header", () => {
  it("holds an Add Connector button with a plus icon that opens the connector catalog", async () => {
    await renderPage();
    expect(screen.getByText("Connector Indexing Status")).toBeInTheDocument();
    const add = screen.getByRole("link", { name: "Add Connector" });
    expect(add).toHaveAttribute("href", "/admin/connectors");
    expect(holdsIcon(add, referencePaths(SvgPlus))).toBe(true);
    // In the header, not the body.
    expect(bodyRow()).not.toContainElement(add);
  });

  it("keeps the xl page with the connector page's narrow gutters", async () => {
    await renderPage();
    const root = document.querySelector('[class~="@container/settings-page"]');
    expect(root).not.toBeNull();
    expect(root).toHaveClass("w-[min(var(--app-container-xl),100%)]");
  });
});

describe("counts card", () => {
  it("puts Active, Total and Paused on one line with the Activities panel button in D", async () => {
    await renderPage();
    const { root, third, part } = lineOf("Active connectors");
    const a = part(screen.getByText("Active connectors"));
    const b = part(screen.getByText("Total documents indexed"));
    const c = part(screen.getByText("Paused connectors"));
    const d = part(screen.getByRole("button", { name: "Hide Activities" }));

    expect(a.parentElement).toBe(root);
    expect(b.parentElement).toBe(root);
    expect(c.parentElement).toBe(third);
    expect(d.parentElement).toBe(third);
    expect(new Set([a, b, c, d]).size).toBe(4);
    expect(within(a).getByText("16")).toBeInTheDocument();
    expect(within(b).getByText("214,316")).toBeInTheDocument();
    expect(within(c).getByText("2")).toBeInTheDocument();
    expect(holdsIcon(d, referencePaths(SvgPanelRight))).toBe(true);
    // The graph card's stats are not on this line.
    expect(root).not.toHaveTextContent("Indexing connectors");
  });

  it("leaves Paused out when the overview does not carry it", async () => {
    await renderPage([FAILED_RUN], false);
    expect(screen.getByText("Total documents indexed")).toBeInTheDocument();
    expect(screen.queryByText("Paused connectors")).toBeNull();
    expect(
      screen.getByRole("button", { name: "Hide Activities" })
    ).toBeInTheDocument();
  });

  it("drops the panel button below 816 px of content, on the body's container", async () => {
    await renderPage();
    let node: HTMLElement | null = screen.getByRole("button", {
      name: "Hide Activities",
    });
    const card = column();
    while (
      node &&
      node !== card &&
      queryClasses(node, "max", "hidden").length === 0
    ) {
      node = node.parentElement;
    }
    expect(node).not.toBe(card);
    expectQueriesBody(node!, "max", "hidden");
  });
});

describe("graph card", () => {
  it("shows Indexing connectors and Docs processed recently with the window picker on the line, the chart under it", async () => {
    await renderPage();
    await screen.findByText("Indexing connectors");
    const { root, third, part } = lineOf("Indexing connectors");
    const a = part(screen.getByText("Indexing connectors"));
    const b = part(screen.getByText("Docs processed recently"));
    expect(a.parentElement).toBe(root);
    expect(b.parentElement).toBe(root);
    expect(within(a).getByText("3")).toBeInTheDocument();
    expect(within(b).getByText("1,842")).toBeInTheDocument();
    expect(
      within(third)
        .getAllByRole("button")
        .some((button) => button.getAttribute("aria-haspopup") !== null)
    ).toBe(true);

    const bars = await screen.findAllByTestId("chart-bar");
    expect(root).not.toContainElement(bars[0]!);
    expect(
      root.compareDocumentPosition(bars[0]!) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    // The counts card sits above the graph card.
    const counts = lineOf("Active connectors").root;
    expect(
      counts.compareDocumentPosition(root) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
  });

  it("a span brushed on the graph card's chart narrows the fleet panel", async () => {
    const user = setupUser();
    const feed = await renderPage();
    await screen.findByText("Indexing connectors");
    const pick = (
      await screen.findAllByRole("button", { name: "pick span" })
    )[0]!;
    // The brushed chart is the graph card's, not another surface's.
    let card: HTMLElement = pick;
    while (!card.contains(screen.getByText("Indexing connectors"))) {
      card = card.parentElement!;
    }
    expect(card).not.toContainElement(screen.getByText("Active connectors"));

    await user.click(pick);
    const since = SPAN.since;
    await waitFor(() =>
      expect(
        feed
          .calls("GET", "/index-monitoring/runs")
          .some((request) => request.url.searchParams.get("since") === since)
      ).toBe(true)
    );
    expect(panel()).not.toBeNull();
  });
});

describe("the fleet Activities panel beside the 640 column", () => {
  it("opens the fleet panel by default when Errors has items, with the panel button selected", async () => {
    await renderPage([FAILED_RUN]);
    await waitFor(() => expect(panel()).not.toBeNull());
    await waitFor(() => expect(cardFor(FAILED_RUN)).not.toBeNull());
    expect(panel()).toContainElement(cardFor(FAILED_RUN));
    const toggle = screen.getByRole("button", { name: "Hide Activities" });
    expect(isSelected(toggle)).toBe(true);
    expect(screen.queryByTestId("indexing-activities")).toBeNull();
  });

  it("sits the 640 column and the 400 panel 16 apart in one row", async () => {
    await renderPage([FAILED_RUN]);
    await waitFor(() => expect(panel()).not.toBeNull());
    const rowElement = bodyRow();
    expect(panel()!.parentElement).toBe(rowElement);
    expect(rowElement).toHaveClass("flex-row");
    expect(rowElement.style.columnGap).toBe("1rem");
    expect(
      classes(column()).some((name) => /(^|:)(max-)?w-\[40rem\]$/.test(name))
    ).toBe(true);
    expectQueriesBody(panel()!, "min", "w-100");
  });

  it("with no open errors the panel starts hidden, the column centers and the button is not selected", async () => {
    const feed = await renderPage([CLEAN_RUN]);
    await settled(feed);
    expect(panel()).toBeNull();
    expect(screen.queryByTestId("indexing-activities")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Show Activities" });
    expect(isSelected(toggle)).toBe(false);
    expect(bodyRow()).toHaveClass("justify-center");
    expect(
      classes(column()).some((name) => /(^|:)(max-)?w-\[40rem\]$/.test(name))
    ).toBe(true);
  });

  it("the panel button hides and shows the panel", async () => {
    const user = setupUser();
    await renderPage([FAILED_RUN]);
    await waitFor(() => expect(panel()).not.toBeNull());

    await user.click(screen.getByRole("button", { name: "Hide Activities" }));
    await waitFor(() => expect(panel()).toBeNull());
    const show = screen.getByRole("button", { name: "Show Activities" });
    expect(isSelected(show)).toBe(false);
    expect(bodyRow()).toHaveClass("justify-center");
    expect(screen.queryByTestId("indexing-activities")).toBeNull();

    await user.click(show);
    await waitFor(() => expect(panel()).not.toBeNull());
    expect(
      isSelected(screen.getByRole("button", { name: "Hide Activities" }))
    ).toBe(true);
  });
});

describe("stacking below 816 px of content", () => {
  it("stacks the row on the body's container like the connector page, not on the viewport", async () => {
    await renderPage([FAILED_RUN]);
    await waitFor(() => expect(panel()).not.toBeNull());
    expectQueriesBody(bodyRow(), "max", "flex-col");
    // The panel follows the column, so stacked it sits at the page bottom.
    expect(bodyRow().lastElementChild).toBe(panel());
    const viewportClasses = [
      bodyRow(),
      panel()!,
      ...Array.from(panel()!.querySelectorAll("*")),
    ].flatMap((element) =>
      classes(element).filter(
        (name) => name.startsWith("max-lg:") || name.startsWith("lg:")
      )
    );
    expect(viewportClasses).toEqual([]);
  });
});

describe("activity hover lifts the connector row", () => {
  it("lifts the hovered activity's connector row and only that row", async () => {
    const user = setupUser();
    await renderPage([FAILED_RUN, CLEAN_RUN]);
    const lifted = await screen.findByTestId(
      `indexing-connector-${SALES_DRIVE.id}`
    );
    const other = screen.getByTestId(`indexing-connector-${SUPPORT_INBOX.id}`);
    await waitFor(() => expect(cardFor(FAILED_RUN)).not.toBeNull());
    const card = cardFor(FAILED_RUN)!;
    expect(lifted).toHaveAttribute("data-shadow", "none");

    await user.hover(card);
    await waitFor(() =>
      expect(lifted).not.toHaveAttribute("data-shadow", "none")
    );
    expect(other).toHaveAttribute("data-shadow", "none");

    await user.unhover(card);
    await waitFor(() => expect(lifted).toHaveAttribute("data-shadow", "none"));
  });
});

describe("copy in every locale", () => {
  type Catalog = Record<string, unknown>;
  const LOCALES: Record<string, Catalog> = {
    ar,
    de,
    en,
    es,
    fr,
    ja,
    ko,
    pt,
    zh,
  };

  function pathsOf(
    node: unknown,
    value: string,
    path: string[] = []
  ): string[][] {
    if (typeof node === "string") return node === value ? [path] : [];
    if (node === null || typeof node !== "object") return [];
    return Object.entries(node as Catalog).flatMap(([key, child]) =>
      pathsOf(child, value, [...path, key])
    );
  }

  function at(catalog: Catalog, path: string[]): unknown {
    return path.reduce<unknown>(
      (node, key) =>
        node !== null && typeof node === "object"
          ? (node as Catalog)[key]
          : undefined,
      catalog
    );
  }

  it.each([
    "Active connectors",
    "Paused connectors",
    "Indexing connectors",
    "Show Activities",
    "Hide Activities",
  ])("%s has a key in all nine locales", (copy) => {
    const paths = pathsOf((en as Catalog).admin, copy, ["admin"]);
    expect(paths).not.toEqual([]);
    for (const [locale, catalog] of Object.entries(LOCALES)) {
      const value = at(catalog, paths[0]!);
      expect({ locale, ok: typeof value === "string" && value !== "" }).toEqual(
        { locale, ok: true }
      );
    }
  });
});
