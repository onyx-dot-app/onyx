/** FE-9: a message card's identity, footer chips and actions, rendered in the activity panel over the faked feed routes. */
import { render, screen, waitFor, within } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import { SvgCheckAll, SvgCheckSquare, SvgRefreshCw } from "@opal/icons";
import englishMessages from "@/i18n/messages/en.json";
import type { ActivityScope } from "@/lib/connectors/ccPair/hooks";
import { getSourceMetadata } from "@/lib/connectors/utils";
import ActivityPanel from "@/views/admin/connectors/ConnectorDetailPage/ActivityPanel";
import {
  READ_ONLY_WIKI,
  SALES_DRIVE,
  cardFor,
  failedChecksRun,
  groupSyncRun,
  holdsIcon,
  indexRun,
  installActivityFeed,
  permSyncRun,
  referencePaths,
  restoreFetch,
  type FeedRun,
} from "@tests/setup/activityFeedTestUtils";

const PAIR: ActivityScope = {
  ccPairId: SALES_DRIVE.id,
  canResolve: true,
  canResolveRuns: true,
};

// A failure with a trace and 21 failed documents, 5 of them still open.
const FAILED = indexRun({
  id: 101,
  status: "failed",
  minutesAgo: 4,
  errorMsg: "Service unavailable.",
  trace: "Traceback: service unavailable",
  errorCount: 21,
  openErrors: 5,
});
const FAILED_NO_DOCS = indexRun({
  id: 102,
  status: "failed",
  minutesAgo: 6,
  errorMsg: "Batch failure.",
});
const ERRORS = indexRun({
  id: 201,
  status: "completed_with_errors",
  minutesAgo: 8,
  openErrors: 3,
});
const RUNNING_ERRORS = indexRun({
  id: 203,
  status: "in_progress",
  minutesAgo: 2,
  openErrors: 4,
});
const SUCCEEDED = indexRun({ id: 401, status: "success", minutesAgo: 15 });
const CHECKS = failedChecksRun({ id: 501, minutesAgo: 9, failedChecks: 2 });
const PERM_SYNC = permSyncRun({
  id: 601,
  status: "completed_with_errors",
  minutesAgo: 10,
  docsWithPermissionErrors: 21,
  trace: "Traceback: permission errors",
});
const GROUP_SYNC = groupSyncRun({
  id: 701,
  status: "failed",
  minutesAgo: 11,
  errorMessage: "Group sync failed.",
  trace: "Traceback: group sync",
});

let REFRESH: string[];
let CHECK_SQUARE: string[];
let CHECK_ALL: string[];
beforeAll(() => {
  REFRESH = referencePaths(SvgRefreshCw);
  CHECK_SQUARE = referencePaths(SvgCheckSquare);
  CHECK_ALL = referencePaths(SvgCheckAll);
});
beforeEach(() => {
  Element.prototype.scrollIntoView = jest.fn();
  window.sessionStorage.clear();
});
afterEach(() => restoreFetch());

function renderPanel(scope: ActivityScope = PAIR) {
  return render(<ActivityPanel scope={scope} title="Activities" />);
}

async function shownCard(run: FeedRun): Promise<HTMLElement> {
  return waitFor(() => {
    const card = cardFor(run);
    expect(card).not.toBeNull();
    return card!;
  });
}

async function chooseAllLevels(user: ReturnType<typeof userEvent.setup>) {
  const levels = /^(All Levels|Failures|Errors|Running|Success|Canceled)$/;
  const trigger = () =>
    screen
      .queryAllByRole("button")
      .find((button) => levels.test((button.textContent ?? "").trim()));
  if (trigger() === undefined) {
    await user.click(
      screen.getByRole("button", { name: /^(Show Filters|Filters)$/ })
    );
  }
  await user.click(await waitFor(() => trigger()!));
  const option = await waitFor(() => {
    const found = ["option", "menuitemradio", "menuitem"]
      .flatMap((role) => screen.queryAllByRole(role))
      .find((candidate) => candidate.textContent?.trim() === "All Levels");
    expect(found).toBeDefined();
    return found!;
  });
  await user.click(option);
}

/** The chip texts in the card's footer, in order. */
function chipTexts(card: HTMLElement): string[] {
  return Array.from(card.querySelectorAll<HTMLElement>("*"))
    .filter((element) =>
      /^(Stack Trace|\d+ (docs?|checks?|users?|groups?) failed( to sync)?)$/.test(
        (element.textContent ?? "").trim()
      )
    )
    .filter(
      (element) =>
        !Array.from(element.children).some(
          (child) => child.textContent?.trim() === element.textContent?.trim()
        )
    )
    .map((element) => element.textContent!.trim())
    .filter((text, index, all) => all.indexOf(text) === index);
}

// ── AC-4: identity ────────────────────────────────────────────────────────

describe("AC-4: card identity", () => {
  it("AC-4: line 1 names the run type on the connector page, and holds the source logo with the connector name as its tooltip on the status page", async () => {
    installActivityFeed([FAILED]);
    const user = userEvent.setup();
    const pairPage = renderPanel();
    const pairCard = await shownCard(FAILED);
    expect(
      within(pairCard).getByText(
        englishMessages.admin.connector.runs.kinds.indexing
      )
    ).toBeInTheDocument();
    expect(within(pairCard).queryByText(SALES_DRIVE.name)).toBeNull();
    pairPage.unmount();

    renderPanel("fleet");
    const card = await shownCard(FAILED);

    expect(within(card).queryByText(SALES_DRIVE.name)).toBeNull();
    const Logo = getSourceMetadata(SALES_DRIVE.source).icon;
    const logoPaths = referencePaths(Logo);
    const logo = Array.from(card.querySelectorAll("svg")).find(
      (svg) =>
        JSON.stringify(
          Array.from(svg.querySelectorAll("path")).map((path) =>
            path.getAttribute("d")
          )
        ) === JSON.stringify(logoPaths)
    );
    expect(logo).toBeDefined();

    await user.hover(logo!);
    expect(await screen.findByRole("tooltip")).toHaveTextContent(
      SALES_DRIVE.name
    );
  });
});

// ── AC-5: footer chips ────────────────────────────────────────────────────

describe("AC-5: footer chips", () => {
  it("AC-5: an index failure shows Stack Trace, then its failed documents counted with the resolved ones; a check run counts its failed checks", async () => {
    installActivityFeed([FAILED, CHECKS]);
    renderPanel();
    const card = await shownCard(FAILED);

    expect(chipTexts(card)).toEqual(["Stack Trace", "21 docs failed"]);
    expect(chipTexts(await shownCard(CHECKS))).toContain("2 checks failed");
  });

  it("AC-5: without per-user and per-group counts (BE-7) sync runs show Stack Trace only", async () => {
    installActivityFeed([PERM_SYNC, GROUP_SYNC]);
    renderPanel();
    const card = await shownCard(PERM_SYNC);

    expect(chipTexts(card)).toEqual(["Stack Trace"]);
    expect(card).not.toHaveTextContent(/failed to sync/);
    expect(chipTexts(await shownCard(GROUP_SYNC))).toEqual(["Stack Trace"]);
  });
});

// ── AC-6: actions ─────────────────────────────────────────────────────────

describe("AC-6: card actions", () => {
  it("AC-6: an index run with open failed documents shows Retry Docs and an icon-only Resolve without Retry, both with their icons", async () => {
    installActivityFeed([ERRORS]);
    const user = userEvent.setup();
    renderPanel();
    const card = await shownCard(ERRORS);
    await user.hover(card);

    const retry = within(card).getByRole("button", { name: "Retry Docs" });
    expect(holdsIcon(retry, REFRESH)).toBe(true);
    const resolve = within(card).getByRole("button", {
      name: "Resolve without Retry",
    });
    expect(resolve).not.toHaveTextContent(/\S/);
    expect(holdsIcon(resolve, CHECK_SQUARE)).toBe(true);
    expect(holdsIcon(resolve, CHECK_ALL)).toBe(false);
    expect(within(card).queryByRole("button", { name: "Resolve" })).toBeNull();
  });

  it("AC-6: Resolve without Retry closes the run through runs/resolve", async () => {
    const feed = installActivityFeed([ERRORS]);
    const user = userEvent.setup();
    renderPanel();
    const card = await shownCard(ERRORS);
    await user.hover(card);

    await user.click(
      within(card).getByRole("button", { name: "Resolve without Retry" })
    );

    await waitFor(() =>
      expect(
        feed.calls("POST", `/cc-pair/${SALES_DRIVE.id}/runs/resolve`)
      ).toHaveLength(1)
    );
    expect(
      feed.calls("POST", `/cc-pair/${SALES_DRIVE.id}/runs/resolve`)[0]!.body
    ).toEqual({
      runs: [{ kind: "indexing", attempt_id: ERRORS.run.attempt.id }],
    });
    expect(feed.calls("POST", "/indexing/targeted-reindex")).toHaveLength(0);
  });

  it("AC-6: a source that cannot re-index single documents shows Resolve only", async () => {
    installActivityFeed([ERRORS]);
    const user = userEvent.setup();
    renderPanel({ ...PAIR, canResolve: false });
    const card = await shownCard(ERRORS);
    await user.hover(card);

    expect(
      within(card).queryByRole("button", { name: "Retry Docs" })
    ).toBeNull();
    const resolve = within(card).getByRole("button", { name: "Resolve" });
    expect(holdsIcon(resolve, CHECK_SQUARE)).toBe(true);
  });

  it("AC-6: a failure without failed documents shows Resolve only", async () => {
    installActivityFeed([FAILED_NO_DOCS]);
    const user = userEvent.setup();
    renderPanel();
    const card = await shownCard(FAILED_NO_DOCS);
    await user.hover(card);

    expect(
      within(card).queryByRole("button", { name: "Retry Docs" })
    ).toBeNull();
    const resolve = within(card).getByRole("button", { name: "Resolve" });
    expect(holdsIcon(resolve, CHECK_SQUARE)).toBe(true);
  });

  it("AC-6: a running run with errors shows Resolve only, and it calls runs/resolve", async () => {
    const feed = installActivityFeed([RUNNING_ERRORS]);
    const user = userEvent.setup();
    renderPanel();
    const card = await shownCard(RUNNING_ERRORS);
    await user.hover(card);

    expect(
      within(card).queryByRole("button", { name: "Retry Docs" })
    ).toBeNull();
    const resolve = within(card).getByRole("button", { name: "Resolve" });
    expect(holdsIcon(resolve, CHECK_SQUARE)).toBe(true);
    await user.click(resolve);

    await waitFor(() =>
      expect(
        feed.calls("POST", `/cc-pair/${SALES_DRIVE.id}/runs/resolve`)
      ).toHaveLength(1)
    );
    expect(
      feed.calls("POST", `/cc-pair/${SALES_DRIVE.id}/runs/resolve`)[0]!.body
    ).toEqual({
      runs: [{ kind: "indexing", attempt_id: RUNNING_ERRORS.run.attempt.id }],
    });
  });

  it("AC-6: a successful run has no actions", async () => {
    installActivityFeed([SUCCEEDED]);
    const user = userEvent.setup();
    renderPanel();
    await chooseAllLevels(user);
    const card = await shownCard(SUCCEEDED);
    await user.hover(card);

    expect(
      within(card).queryByRole("button", {
        name: /^(Resolve|Resolve without Retry|Retry Docs)$/,
      })
    ).toBeNull();
  });

  it("AC-6: on the status page only the pairs the viewer operates show Retry Docs and Resolve", async () => {
    const readOnly = indexRun({
      id: 202,
      status: "completed_with_errors",
      minutesAgo: 9,
      openErrors: 3,
      ccPairId: READ_ONLY_WIKI.id,
    });
    installActivityFeed([ERRORS, readOnly]);
    const user = userEvent.setup();
    renderPanel("fleet");
    const operable = await shownCard(ERRORS);
    await user.hover(operable);
    expect(
      within(operable).getByRole("button", { name: "Retry Docs" })
    ).toBeInTheDocument();

    const card = await shownCard(readOnly);
    await user.hover(card);
    expect(
      within(card).queryByRole("button", {
        name: /^(Resolve|Resolve without Retry|Retry Docs)$/,
      })
    ).toBeNull();
  });
});
