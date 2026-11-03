/** FE-9: the activity panel's levels, sections, header counts, Resolve all, Connectors filter, width, default visibility, empty state and chart links. The feed routes are faked with the backend's filter semantics. */
import { act, render, screen, waitFor, within } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { Button } from "@opal/components";
import { SvgLongWait } from "@opal/illustrations";
import englishMessages from "@/i18n/messages/en.json";
import type { ActivityScope } from "@/lib/connectors/ccPair/hooks";
import ActivityPanel, {
  useActivityPanelOpen,
} from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import {
  SALES_DRIVE,
  SUPPORT_INBOX,
  cardFor,
  cardKeys,
  indexRun,
  installActivityFeed,
  minutesAgo,
  referencePaths,
  restoreFetch,
  runKey,
  shownSections,
  type ActivityFeed,
  type FeedRun,
} from "@tests/setup/activityFeedTestUtils";

const PAIR: ActivityScope = {
  ccPairId: SALES_DRIVE.id,
  canResolve: true,
  canResolveRuns: true,
};

// Open failures, newest first.
const F1 = indexRun({
  id: 101,
  status: "failed",
  minutesAgo: 5,
  errorMsg: "Service unavailable. Connection reset by peer.",
  trace: "Traceback: service unavailable",
});
const F2 = indexRun({
  id: 102,
  status: "failed",
  minutesAgo: 12,
  errorMsg: "Batch failure.",
});
// Open errors: two finished, and the newest run of all still running with errors.
const E1 = indexRun({
  id: 201,
  status: "completed_with_errors",
  minutesAgo: 8,
  openErrors: 3,
});
const E2 = indexRun({
  id: 202,
  status: "completed_with_errors",
  minutesAgo: 20,
  openErrors: 2,
});
const ER = indexRun({
  id: 203,
  status: "in_progress",
  minutesAgo: 2,
  openErrors: 4,
});
const R1 = indexRun({ id: 301, status: "in_progress", minutesAgo: 1 });
const S1 = indexRun({ id: 401, status: "success", minutesAgo: 15 });
const C1 = indexRun({ id: 501, status: "canceled", minutesAgo: 18 });
const Q1 = indexRun({ id: 601, status: "not_started", minutesAgo: 0 });
// Resolved: a failure and a run whose errors were all closed.
const RF = indexRun({
  id: 701,
  status: "failed",
  minutesAgo: 25,
  errorMsg: "Old failure.",
  resolved: true,
});
const RE = indexRun({
  id: 702,
  status: "completed_with_errors",
  minutesAgo: 22,
  errorCount: 3,
  openErrors: 0,
  resolved: true,
});

const POOL = [F1, F2, E1, E2, ER, R1, S1, C1, Q1, RF, RE];
const LEVELS = [
  "All Levels",
  "Failures",
  "Errors",
  "Running",
  "Success",
  "Canceled",
];
const keys = (...runs: FeedRun[]) => runs.map(runKey);
type User = ReturnType<typeof userEvent.setup>;

let scrolled: Element[] = [];
beforeEach(() => {
  scrolled = [];
  Element.prototype.scrollIntoView = function (this: Element) {
    scrolled.push(this);
  };
  window.sessionStorage.clear();
});
afterEach(() => restoreFetch());

function renderPanel(
  scope: ActivityScope = PAIR,
  props: Partial<React.ComponentProps<typeof ActivityPanel>> = {}
) {
  return render(<ActivityPanel scope={scope} title="Activities" {...props} />);
}

async function loaded(...runs: FeedRun[]) {
  await waitFor(() => {
    for (const run of runs) expect(cardFor(run)).not.toBeNull();
  });
}

function levelTrigger(): HTMLElement | null {
  return (
    screen
      .queryAllByRole("button")
      .find((button) => LEVELS.includes((button.textContent ?? "").trim())) ??
    null
  );
}

/** Shows the filter bar when it sits behind its header toggle. */
async function openFilters(user: User) {
  if (levelTrigger() !== null) return;
  await user.click(
    screen.getByRole("button", { name: /^(Show Filters|Filters)$/ })
  );
  await waitFor(() => expect(levelTrigger()).not.toBeNull());
}

async function menuOptions(): Promise<HTMLElement[]> {
  return waitFor(() => {
    const found = ["option", "menuitemradio", "menuitem", "menuitemcheckbox"]
      .flatMap((role) => screen.queryAllByRole(role))
      .filter((option) => option.textContent?.trim());
    expect(found.length).toBeGreaterThan(0);
    return found;
  });
}

async function chooseLevel(user: User, level: string) {
  await openFilters(user);
  await user.click(levelTrigger()!);
  const option = (await menuOptions()).find(
    (candidate) => candidate.textContent?.trim() === level
  );
  if (option === undefined) throw new Error(`no level option ${level}`);
  await user.click(option);
}

async function toggleResolved(user: User) {
  await openFilters(user);
  await user.click(screen.getByRole("button", { name: /^Resolved$/ }));
}

// ── AC-1: levels ──────────────────────────────────────────────────────────

describe("AC-1: six levels, Errors by default", () => {
  it.each<[string, ActivityScope]>([
    ["connector page", PAIR],
    ["status page", "fleet"],
  ])("AC-1: the %s offers the six levels in order", async (_, scope) => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel(scope);
    await openFilters(user);

    expect(levelTrigger()).toHaveTextContent(/^Errors$/);
    await user.click(levelTrigger()!);
    const options = (await menuOptions()).map((option) =>
      option.textContent?.trim()
    );
    expect(options).toEqual(LEVELS);
  });

  it("AC-1: Errors (default) on the status page shows failures and errors, running ones with errors included, and nothing else", async () => {
    installActivityFeed(POOL);
    renderPanel("fleet");
    await loaded(F1, F2, E1, E2, ER);

    expect(new Set(cardKeys())).toEqual(new Set(keys(F1, F2, E1, E2, ER)));
  });

  it("AC-1: Running shows running runs with and without errors", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, "Running");

    await waitFor(() =>
      expect(new Set(cardKeys())).toEqual(new Set(keys(ER, R1)))
    );
  });

  it.each<[string, FeedRun[]]>([
    ["Success", [S1]],
    ["Canceled", [C1]],
  ])("AC-1: %s shows only its runs", async (level, expected) => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, level);

    await waitFor(() =>
      expect(new Set(cardKeys())).toEqual(new Set(keys(...expected)))
    );
  });

  it("AC-1: All Levels shows every open run except the scheduled one", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, "All Levels");

    await waitFor(() =>
      expect(new Set(cardKeys())).toEqual(
        new Set(keys(F1, F2, E1, E2, ER, R1, S1, C1))
      )
    );
    expect(cardFor(Q1)).toBeNull();
  });
});

// ── AC-2 and AC-3: sections ───────────────────────────────────────────────

describe("AC-2: sections in spec order", () => {
  it("AC-2: Errors lists N Failures then N Errors, newest first, the running run with errors last", async () => {
    installActivityFeed(POOL);
    renderPanel();
    await loaded(F1, F2, E1, E2, ER);

    expect(shownSections()).toEqual([
      { title: "2 Failures", keys: keys(F1, F2) },
      { title: "3 Errors", keys: keys(E1, E2, ER) },
    ]);
  });

  it("AC-2: All Levels adds N Running, Success and Canceled, the last two without counts", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, "All Levels");

    await waitFor(() =>
      expect(shownSections()).toEqual([
        { title: "2 Failures", keys: keys(F1, F2) },
        { title: "3 Errors", keys: keys(E1, E2, ER) },
        { title: "1 Running", keys: keys(R1) },
        { title: "Success", keys: keys(S1) },
        { title: "Canceled", keys: keys(C1) },
      ])
    );
  });

  it("AC-2: Running keeps the running run with errors above the Running section", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, "Running");

    await waitFor(() => expect(cardKeys()).toEqual(keys(ER, R1)));
    const titles = shownSections().map((section) => section.title);
    expect(titles[titles.length - 1]).toBe("1 Running");
  });

  it("AC-2: no Running section without running runs", async () => {
    installActivityFeed([F1, S1]);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, "All Levels");

    await waitFor(() => expect(cardFor(S1)).not.toBeNull());
    expect(
      shownSections().some((section) => /Running/.test(section.title))
    ).toBe(false);
  });
});

describe("AC-3: the Resolved toggle", () => {
  it("AC-3: All Levels with Resolved puts Resolved after the open sections, failures before errors, before Success and Canceled", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await chooseLevel(user, "All Levels");
    await toggleResolved(user);

    await waitFor(() =>
      expect(shownSections()).toEqual([
        { title: "2 Failures", keys: keys(F1, F2) },
        { title: "3 Errors", keys: keys(E1, E2, ER) },
        { title: "1 Running", keys: keys(R1) },
        { title: "Resolved", keys: keys(RF, RE) },
        { title: "Success", keys: keys(S1) },
        { title: "Canceled", keys: keys(C1) },
      ])
    );
  });

  it("AC-3: Errors with Resolved keeps the open sections and adds the level's resolved runs", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await toggleResolved(user);

    await waitFor(() =>
      expect(shownSections()).toEqual([
        { title: "2 Failures", keys: keys(F1, F2) },
        { title: "3 Errors", keys: keys(E1, E2, ER) },
        { title: "Resolved", keys: keys(RF, RE) },
      ])
    );
  });
});

// ── AC-11: header counts ──────────────────────────────────────────────────

describe("AC-11: header counts", () => {
  function expectCounts() {
    // Open failures 2, open errors 3 (the running run with errors included).
    expect(screen.getAllByText("2", { exact: true }).length).toBeGreaterThan(0);
    expect(screen.getAllByText("3", { exact: true }).length).toBeGreaterThan(0);
  }

  it("AC-11: the level, the Resolved toggle and the search leave the counts as they are", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1);
    await waitFor(expectCounts);

    await chooseLevel(user, "Success");
    await waitFor(() => expect(cardFor(S1)).not.toBeNull());
    expectCounts();

    await toggleResolved(user);
    expectCounts();

    await user.type(
      screen.getByPlaceholderText(
        englishMessages.admin.connector.activity.search.placeholder
      ),
      "no such message"
    );
    await waitFor(() => expect(cardFor(S1)).toBeNull());
    expectCounts();
  });
});

// ── AC-7: Resolve all ─────────────────────────────────────────────────────

async function openResolveAll(user: User) {
  const button = await screen.findByRole("button", { name: /^Resolve All$/ });
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
  return screen.findByRole("dialog");
}

describe("AC-7: Resolve all asks to confirm", () => {
  it("AC-7: the confirmation counts what it resolves and says nothing is retried", async () => {
    installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1, ER);

    const dialog = await openResolveAll(user);
    expect(
      within(dialog).getByText("Resolve all shown activities")
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(dialog).toHaveTextContent(
        "This resolves the 5 activities that match the current filter: 2 failures and 3 runs with errors."
      )
    );
    expect(dialog).toHaveTextContent("Onyx does not retry their failed items.");
    expect(dialog).toHaveTextContent(
      "A run that is still running can report new errors. They show as open again."
    );
    expect(
      within(dialog).getByRole("button", { name: "Cancel" })
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Resolve All" })
    ).toBeInTheDocument();
  });

  it("AC-7: Cancel resolves nothing; Resolve All posts the pair's resolve-matching for the shown levels", async () => {
    const feed = installActivityFeed(POOL);
    const user = userEvent.setup();
    renderPanel();
    await loaded(F1, ER);

    let dialog = await openResolveAll(user);
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(feed.calls("POST", "/runs/resolve-matching")).toHaveLength(0);

    dialog = await openResolveAll(user);
    await user.click(
      within(dialog).getByRole("button", { name: "Resolve All" })
    );
    await waitFor(() =>
      expect(
        feed.calls("POST", `/cc-pair/${SALES_DRIVE.id}/runs/resolve-matching`)
      ).toHaveLength(1)
    );
    const [request] = feed.calls("POST", "/runs/resolve-matching");
    // Errors covers failures and errors, so no single backend level narrows it.
    expect(request!.body?.level ?? null).toBeNull();
  });
});

// ── AC-8: Connectors filter ───────────────────────────────────────────────

describe("AC-8: Connectors filter", () => {
  const INBOX_FAILURE = indexRun({
    id: 901,
    status: "failed",
    minutesAgo: 3,
    errorMsg: "Inbox failure.",
    ccPairId: SUPPORT_INBOX.id,
  });
  const FLEET_POOL = [F1, INBOX_FAILURE];

  async function pickConnector(user: User, name: string) {
    await openFilters(user);
    await user.click(screen.getByRole("button", { name: /Connectors/ }));
    const option = await waitFor(() => {
      const found = [
        "option",
        "menuitemcheckbox",
        "checkbox",
        "menuitem",
        "menuitemradio",
      ]
        .flatMap((role) => screen.queryAllByRole(role))
        .find((candidate) => candidate.textContent?.includes(name));
      expect(found).toBeDefined();
      return found!;
    });
    await user.click(option);
    await user.keyboard("{Escape}");
  }

  it("AC-8: only the status page has the Connectors filter, and it filters the feed with cc_pair_ids", async () => {
    const feed = installActivityFeed(FLEET_POOL);
    const user = userEvent.setup();
    const pairPage = renderPanel();
    await loaded(F1);
    await openFilters(user);
    expect(screen.queryByRole("button", { name: /Connectors/ })).toBeNull();
    pairPage.unmount();

    renderPanel("fleet");
    await loaded(F1, INBOX_FAILURE);

    await pickConnector(user, SUPPORT_INBOX.name);

    await waitFor(() =>
      expect(
        feed
          .calls("GET", "/index-monitoring/runs")
          .some(
            (request) =>
              request.url.searchParams.getAll("cc_pair_ids").join(",") ===
              String(SUPPORT_INBOX.id)
          )
      ).toBe(true)
    );
    await waitFor(() => expect(cardFor(F1)).toBeNull());
    expect(cardFor(INBOX_FAILURE)).not.toBeNull();
  });

  it("AC-7, AC-8: Resolve all on the status page sends the chosen cc_pair_ids", async () => {
    const feed = installActivityFeed(FLEET_POOL);
    const user = userEvent.setup();
    renderPanel("fleet");
    await loaded(F1);
    await pickConnector(user, SUPPORT_INBOX.name);
    await waitFor(() => expect(cardFor(F1)).toBeNull());

    const dialog = await openResolveAll(user);
    await user.click(
      within(dialog).getByRole("button", { name: "Resolve All" })
    );
    await waitFor(() =>
      expect(feed.calls("POST", "/index-monitoring/runs/resolve")).toHaveLength(
        1
      )
    );
    const [request] = feed.calls("POST", "/index-monitoring/runs/resolve");
    expect(request!.body?.cc_pair_ids).toEqual([SUPPORT_INBOX.id]);
  });
});

// ── Width ─────────────────────────────────────────────────────────────────

describe("Side panel width", () => {
  it("is 400 px wide", async () => {
    installActivityFeed(POOL);
    const { container } = renderPanel();
    await loaded(F1);

    const panel = container.querySelector<HTMLElement>(
      '[data-testid="connector-activity"]'
    )!;
    const width = /(^|:)(w|max-w|basis|min-w)-(100|\[400px\]|\[25rem\])$/;
    const sized = [panel, ...Array.from(panel.querySelectorAll("*"))].some(
      (element) =>
        Array.from(element.classList).some((name) => width.test(name))
    );
    expect(sized).toBe(true);
    expect(container.innerHTML).not.toMatch(/max-w-104/);
  });
});

// ── AC-9: open by default only when Errors has items ──────────────────────

function OpenProbe({ scope }: { scope: ActivityScope }) {
  const { open, setOpen } = useActivityPanelOpen(scope);
  return (
    <>
      <output data-testid="open">{String(open)}</output>
      <Button onClick={() => setOpen(!open)}>toggle</Button>
    </>
  );
}

async function settled(feed: ActivityFeed) {
  await waitFor(() =>
    expect(
      feed.requests.some((request) => request.url.pathname.endsWith("/runs"))
    ).toBe(true)
  );
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 50));
  });
}

describe("AC-9: default visibility", () => {
  it.each<[string, FeedRun[]]>([
    ["an open failure", [F1, S1]],
    ["an open error", [E1]],
    ["a running run with errors", [ER, R1]],
  ])("AC-9: opens when the Errors level holds %s", async (_, pool) => {
    installActivityFeed(pool);
    render(<OpenProbe scope={PAIR} />);

    await waitFor(() =>
      expect(screen.getByTestId("open")).toHaveTextContent("true")
    );
  });

  it("AC-9: stays hidden when the only activity is running runs without errors, successes and resolved runs", async () => {
    const feed = installActivityFeed([R1, S1, C1, RF]);
    render(<OpenProbe scope={PAIR} />);
    await settled(feed);

    expect(screen.getByTestId("open")).toHaveTextContent("false");
  });

  it("AC-9: the admin's choice holds for the session", async () => {
    installActivityFeed([F1]);
    const user = userEvent.setup();
    const first = render(<OpenProbe scope={PAIR} />);
    await waitFor(() =>
      expect(screen.getByTestId("open")).toHaveTextContent("true")
    );
    await user.click(screen.getByRole("button", { name: "toggle" }));
    expect(screen.getByTestId("open")).toHaveTextContent("false");
    first.unmount();

    restoreFetch();
    const feed = installActivityFeed([F1]);
    render(<OpenProbe scope={PAIR} />);
    await settled(feed);
    expect(screen.getByTestId("open")).toHaveTextContent("false");
  });
});

// ── AC-10: empty state ────────────────────────────────────────────────────

describe("AC-10: empty panel", () => {
  const LAST_HOUR = { since: minutesAgo(60), until: minutesAgo(-1) };
  const OLD = indexRun({
    id: 801,
    status: "failed",
    minutesAgo: 3 * 24 * 60,
    errorMsg: "Old outage.",
  });

  function longWait(container: HTMLElement): SVGElement | null {
    const paths = JSON.stringify(referencePaths(SvgLongWait));
    return (
      Array.from(container.querySelectorAll("svg")).find(
        (svg) =>
          JSON.stringify(
            Array.from(svg.querySelectorAll("path")).map((path) =>
              path.getAttribute("d")
            )
          ) === paths
      ) ?? null
    );
  }

  it("AC-10: shows the long-wait illustration at 64 and Past Activities when older items exist", async () => {
    installActivityFeed([OLD]);
    const { container } = renderPanel(PAIR, { range: LAST_HOUR });

    expect(await screen.findByText("No recent activity")).toBeInTheDocument();
    expect(await screen.findByText("Past Activities")).toBeInTheDocument();
    const svg = longWait(container);
    expect(svg).not.toBeNull();
    const at64 =
      svg!.getAttribute("width") === "64" ||
      /(^|\s)(w-16|size-16|w-\[64px\]|w-\[4rem\])(\s|$)/.test(
        svg!.getAttribute("class") ?? ""
      );
    expect(at64).toBe(true);
  });

  it("AC-10: no Past Activities when nothing older exists", async () => {
    const feed = installActivityFeed([]);
    renderPanel(PAIR, { range: LAST_HOUR });

    expect(await screen.findByText("No recent activity")).toBeInTheDocument();
    await settled(feed);
    expect(screen.queryByText("Past Activities")).toBeNull();
  });
});

// ── Chart links (5.2) ─────────────────────────────────────────────────────

function subtree(card: HTMLElement): HTMLElement[] {
  return [card, ...Array.from(card.querySelectorAll<HTMLElement>("*"))];
}

function hasLift(card: HTMLElement): boolean {
  return subtree(card).some(
    (element) =>
      (element.dataset.shadow !== undefined &&
        element.dataset.shadow !== "none") ||
      Array.from(element.classList).some((name) =>
        /^shadow-(01|02|03|sm|md|lg|box)/.test(name)
      )
  );
}

function hasOutline(card: HTMLElement): boolean {
  return subtree(card).some((element) =>
    Array.from(element.classList).some((name) =>
      /^(outline-solid|outline-1|outline-2|ring-1|ring-2)$/.test(name)
    )
  );
}

describe("Chart links", () => {
  it("hovering an index run's card reports its attempt to the chart, and leaving clears it", async () => {
    installActivityFeed(POOL);
    const onHoverAttempt = jest.fn();
    const user = userEvent.setup();
    renderPanel(PAIR, { onHoverAttempt });
    await loaded(E1);

    await user.hover(cardFor(E1)!);
    expect(onHoverAttempt).toHaveBeenLastCalledWith(E1.run.attempt.id);
    await user.unhover(cardFor(E1)!);
    expect(onHoverAttempt).toHaveBeenLastCalledWith(null);
  });

  it("a focused attempt scrolls its card into view and lifts it", async () => {
    installActivityFeed(POOL);
    const { rerender } = renderPanel(PAIR, { focusAttemptId: null });
    await loaded(F2);
    expect(hasLift(cardFor(F2)!)).toBe(false);

    rerender(
      <ActivityPanel
        scope={PAIR}
        title="Activities"
        focusAttemptId={F2.run.attempt.id}
      />
    );

    await waitFor(() => {
      const card = cardFor(F2)!;
      expect(scrolled.some((element) => card.contains(element))).toBe(true);
      expect(hasLift(card)).toBe(true);
    });
  });

  it("a hovered chart line outlines its activities only", async () => {
    installActivityFeed(POOL);
    renderPanel(PAIR, { outlinedAttemptIds: [E2.run.attempt.id] });
    await loaded(E1, E2);

    await waitFor(() => expect(hasOutline(cardFor(E2)!)).toBe(true));
    expect(hasOutline(cardFor(E1)!)).toBe(false);
  });
});
