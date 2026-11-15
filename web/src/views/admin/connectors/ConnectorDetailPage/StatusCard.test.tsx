/** The connector page's Indexing and Permissions Sync status cards on LineLayout, without the estimate bar. */
import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
  within,
} from "@tests/setup/test-utils";
import { SvgListCheck, SvgScissors } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  CC_PAIR_RUN_KINDS,
  ConnectorCredentialPairStatus,
  PermissionSyncStatusEnum,
  type CCPairFullInfo,
  type CCPairRun,
  type CCPairRunKind,
  type CCPairRunsResponse,
  type DocumentTypeCount,
  type CCPairDocumentTypeBreakdown,
  type PaginatedIndexAttempts,
} from "@/lib/connectors/types";
import StatusCard from "@/views/admin/connectors/ConnectorDetailPage/StatusCard";
import englishMessages from "@/i18n/messages/en.json";

const CC_PAIR_ID = 7;
const MINUTE_MS = 60_000;
const DAY_MS = 24 * 60 * MINUTE_MS;

function isoAgo(ms: number): string {
  return new Date(Date.now() - ms).toISOString();
}

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

const KEYS = {
  title: "admin.connector.statusCard.title",
  rate: "admin.connector.runs.detail.rate",
  lastIndexed: "admin.connector.statusCard.lastIndexed.value",
  deletionStarted: "admin.connector.statusCard.deletionStarted.value",
  indexedLabel: "admin.connector.statusCard.documents.indexedLabel",
  showActivities: "admin.connector.statusCard.actions.showActivities",
  hideActivities: "admin.connector.statusCard.actions.hideActivities",
  viewDetails: "admin.connector.statusCard.actions.viewDetails",
  hideDetails: "admin.connector.statusCard.actions.hideDetails",
  viewPruningRun: "admin.connector.statusCard.actions.viewPruningRun",
  viewChecksRun: "admin.connector.statusCard.actions.viewChecksRun",
  permissionsTitle: "admin.connector.statusCard.sync.permissionsTitle",
  docsLabel: "admin.connector.statusCard.sync.docsLabel",
  groupsLabel: "admin.connector.statusCard.sync.groupsLabel",
  waitingForFirstIndex: "admin.connector.statusCard.sync.waitingForFirstIndex",
  lastSynced: "admin.connector.statusCard.sync.last",
  neverTooltip: "admin.connector.statusCard.sync.neverTooltip",
  stageHint: "admin.connector.runs.actions.stages",
  viewErrors: "admin.indexing.list.actions.viewErrors",
  startingSync: "admin.connector.runs.detail.starting",
};

function badge(key: string): string {
  return copy(`admin.status.badges.${key}`);
}

// ── Hook boundary ───────────────────────────────────────────────────────────

let mockIndexAttempts: PaginatedIndexAttempts = { items: [], total_items: 0 };
/** The newest run of each kind, as the runs feed returns it. */
let mockLatestRuns: Partial<Record<CCPairRunKind, CCPairRun>> = {};
/** The kinds the pair's source runs. */
let mockSourceKinds: CCPairRunKind[] = [];
/** The kinds whose runs feed fails to load. */
let mockFailedKinds: CCPairRunKind[] = [];

function mockRunsResponse(kind: CCPairRunKind): CCPairRunsResponse {
  const run = mockLatestRuns[kind];
  return {
    items: run === undefined ? [] : [run],
    total_items: run === undefined ? 0 : 1,
    kinds: mockSourceKinds,
    status_counts: { running: 0, succeeded: 0, failed: 0, canceled: 0 },
  };
}

jest.mock("@/lib/connectors/ccPair/hooks", () => {
  const actual = jest.requireActual("@/lib/connectors/ccPair/hooks");
  return {
    ...actual,
    useLatestIndexAttempt: () => ({
      data: mockIndexAttempts,
      error: undefined,
      isLoading: false,
      isValidating: false,
      mutate: jest.fn(),
    }),
    useLatestCCPairRun: (
      _ccPairId: number,
      kind: CCPairRunKind,
      enabled: boolean
    ) => ({
      data:
        enabled && !mockFailedKinds.includes(kind)
          ? mockRunsResponse(kind)
          : undefined,
      error:
        enabled && mockFailedKinds.includes(kind)
          ? new Error("runs feed failed")
          : undefined,
      isLoading: false,
      isValidating: false,
      mutate: jest.fn(),
    }),
  };
});

const realFetch = global.fetch;
beforeEach(() => {
  // Anything the card reads past the hooks stays pending.
  global.fetch = jest.fn(() => new Promise<Response>(() => {})) as typeof fetch;
});
afterEach(() => {
  global.fetch = realFetch;
  mockIndexAttempts = { items: [], total_items: 0 };
  mockLatestRuns = {};
  mockSourceKinds = [];
  mockFailedKinds = [];
});

// ── Fixtures ────────────────────────────────────────────────────────────────

const ALL_KINDS: CCPairRunKind[] = [...CC_PAIR_RUN_KINDS];

/** An active, permission-synced Confluence pair that indexed 2 minutes ago. */
function ccPair(overrides: Partial<CCPairFullInfo> = {}): CCPairFullInfo {
  return {
    id: CC_PAIR_ID,
    name: "Policy knowledge",
    status: ConnectorCredentialPairStatus.ACTIVE,
    in_repeated_error_state: false,
    num_docs_indexed: 3248,
    connector: {
      id: 11,
      name: "Policy knowledge",
      source: "confluence",
      input_type: "poll",
      connector_specific_config: {},
      refresh_freq: 1800,
      prune_freq: 86400,
      check_freq: null,
      indexing_start: null,
      access_type: "sync",
      credential_ids: [12],
      time_created: isoAgo(200 * DAY_MS),
      time_updated: isoAgo(200 * DAY_MS),
    },
    credential: {
      id: 12,
      credential_json: {},
      admin_public: true,
      source: "confluence",
      name: "Confluence account",
      user_id: null,
      user_email: null,
      user_personal_name: null,
      time_created: isoAgo(200 * DAY_MS),
      time_updated: isoAgo(200 * DAY_MS),
    },
    number_of_index_attempts: 15,
    last_index_attempt_status: "success",
    latest_deletion_attempt: null,
    access_type: "sync",
    is_editable_for_current_user: true,
    permissions: { operate: true, edit: true, delete: true },
    deletion_failure_message: null,
    indexing: false,
    creator: null,
    creator_email: null,
    last_indexed: isoAgo(2 * MINUTE_MS + 10_000),
    last_pruned: null,
    last_full_permission_sync: null,
    last_time_perm_sync: isoAgo(2 * MINUTE_MS + 10_000),
    last_time_external_group_sync: isoAgo(2 * MINUTE_MS + 10_000),
    overall_indexing_speed: 24.23,
    latest_checkpoint_description: null,
    last_permission_sync_attempt_status: PermissionSyncStatusEnum.SUCCESS,
    permission_syncing: false,
    last_permission_sync_attempt_finished: isoAgo(2 * MINUTE_MS + 10_000),
    last_permission_sync_attempt_error_message: null,
    supports_doc_permission_sync: true,
    supports_targeted_reindex: true,
    pending_backfills: [],
    has_named_checks: false,
    indexing_hold: null,
    queue_position: null,
    ...overrides,
  } as CCPairFullInfo;
}

type IndexAttempt = PaginatedIndexAttempts["items"][number];

function indexAttempt(overrides: Partial<IndexAttempt> = {}): IndexAttempt {
  return {
    id: 30,
    status: "success",
    from_beginning: false,
    new_docs_indexed: 100,
    docs_removed_from_index: 0,
    total_docs_indexed: 125,
    error_msg: null,
    error_count: 0,
    open_error_count: 0,
    open_doc_error_count: 0,
    full_exception_trace: null,
    time_started: isoAgo(8 * MINUTE_MS),
    time_updated: isoAgo(2 * MINUTE_MS),
    time_finished: isoAgo(2 * MINUTE_MS),
    is_new_model: false,
    is_backfill: false,
    ...overrides,
  } as IndexAttempt;
}

function docSyncRun(
  overrides: Partial<
    Extract<CCPairRun, { kind: "doc_permission_sync" }>["attempt"]
  > = {}
): CCPairRun {
  return {
    kind: "doc_permission_sync",
    time_created: isoAgo(5 * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    attempt: {
      id: 51,
      status: PermissionSyncStatusEnum.SUCCESS,
      error_message: null,
      full_exception_trace: null,
      total_docs_synced: 248,
      docs_with_permission_errors: 0,
      time_created: isoAgo(5 * MINUTE_MS),
      time_started: isoAgo(5 * MINUTE_MS),
      time_finished: isoAgo(2 * MINUTE_MS + 10_000),
      ...overrides,
    },
  };
}

function groupSyncRun(): CCPairRun {
  return {
    kind: "group_sync",
    time_created: isoAgo(5 * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    attempt: {
      id: 61,
      status: PermissionSyncStatusEnum.SUCCESS,
      error_message: null,
      full_exception_trace: null,
      total_users_processed: 12,
      total_groups_processed: 4,
      total_group_memberships_synced: 49,
      failed_users: 0,
      failed_groups: 0,
      open_error_count: 0,
      time_created: isoAgo(5 * MINUTE_MS),
      time_started: isoAgo(5 * MINUTE_MS),
      time_finished: isoAgo(2 * MINUTE_MS + 10_000),
    },
  };
}

const PRUNE_RUN_ID = 44;
const CHECK_RUN_ID = 45;

function pruneRun(): CCPairRun {
  return {
    kind: "pruning",
    time_created: isoAgo(60 * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    attempt: {
      id: PRUNE_RUN_ID,
      status: "success",
      docs_removed: 15,
      docs_failed: 0,
      error_message: null,
      time_created: isoAgo(60 * MINUTE_MS),
      time_started: isoAgo(60 * MINUTE_MS),
      time_finished: isoAgo(58 * MINUTE_MS),
    },
  };
}

function checkRun(): CCPairRun {
  return {
    kind: "checks",
    time_created: isoAgo(90 * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    attempt: {
      id: CHECK_RUN_ID,
      status: "passed",
      trigger: "scheduled",
      check_results: [],
      error_message: null,
      time_created: isoAgo(90 * MINUTE_MS),
      time_started: isoAgo(90 * MINUTE_MS),
      time_finished: isoAgo(89 * MINUTE_MS),
    },
  };
}

/** Indexed 2 minutes ago, with a finished prune, check run, permission sync and group sync. */
function seedIndexed() {
  mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
  mockSourceKinds = ALL_KINDS;
  mockLatestRuns = {
    doc_permission_sync: docSyncRun(),
    group_sync: groupSyncRun(),
    pruning: pruneRun(),
    checks: checkRun(),
  };
  return ccPair();
}

/** An index run in flight at 24.23 docs/min with 3 open errors. */
function seedIndexing() {
  const started = Date.now() - 101 * MINUTE_MS;
  mockIndexAttempts = {
    items: [
      indexAttempt({
        id: 31,
        status: "in_progress",
        total_docs_indexed: 2423,
        time_started: new Date(started).toISOString(),
        time_updated: new Date(started + 100 * MINUTE_MS).toISOString(),
        error_count: 3,
        open_error_count: 3,
        open_doc_error_count: 3,
        time_finished: null,
      }),
    ],
    total_items: 1,
  };
  mockSourceKinds = ALL_KINDS;
  mockLatestRuns = {
    doc_permission_sync: docSyncRun(),
    group_sync: groupSyncRun(),
  };
  return ccPair({
    indexing: true,
    last_index_attempt_status: "in_progress",
  });
}

// ── Helpers ─────────────────────────────────────────────────────────────────

interface RenderOptions {
  panelOpen?: boolean;
}

function renderCard(
  pair: CCPairFullInfo,
  { panelOpen = true }: RenderOptions = {}
) {
  const onOpenRun = jest.fn();
  const onFocusErrors = jest.fn();
  const onTogglePanel = jest.fn();
  const view = render(
    <StatusCard
      ccPair={pair}
      onStartIndexing={null}
      startingIndexing={false}
      onViewChecks={jest.fn()}
      onOpenRun={onOpenRun}
      onFocusErrors={onFocusErrors}
      panelOpen={panelOpen}
      onTogglePanel={onTogglePanel}
    />
  );
  return { ...view, onOpenRun, onFocusErrors, onTogglePanel };
}

function cards(): HTMLElement[] {
  return screen.getAllByTestId("status-card");
}

function indexingCard(): HTMLElement {
  return cards()[0]!;
}

function permissionsCard(): HTMLElement {
  const all = cards();
  expect(all).toHaveLength(2);
  return all[1]!;
}

/** The card's LineLayout: its third column (C and D) and the part of the line holding an element. */
function lineOf(card: HTMLElement) {
  const third = card.querySelector<HTMLElement>(".basis-1\\/3");
  expect(third).not.toBeNull();
  const root = third!.parentElement!;
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
  return { third: third!, root, part };
}

/** The status tag whose label reads `label`. */
function tagOf(container: HTMLElement, label: string): HTMLElement {
  const tag = within(container)
    .getByText(label, { exact: true })
    .closest<HTMLElement>(".opal-badge");
  expect(tag).not.toBeNull();
  return tag!;
}

function iconPaths(svg: Element | null): string[] {
  return Array.from(svg?.querySelectorAll("path") ?? []).map(
    (path) => path.getAttribute("d") ?? ""
  );
}

function referencePaths(Icon: IconFunctionComponent): string[] {
  const { container, unmount } = render(<Icon size={16} />);
  const paths = iconPaths(container.querySelector("svg"));
  unmount();
  return paths;
}

/** Selected by `aria-pressed` or Opal's stateful `data-interactive-state`. */
function isSelected(button: HTMLElement): boolean {
  return (
    button.getAttribute("aria-pressed") === "true" ||
    button.closest('[data-interactive-state="selected"]') !== null ||
    button.querySelector('[data-interactive-state="selected"]') !== null
  );
}

function withWhen(key: string, when: string): string {
  return copy(key).replace("{when}", when);
}

// ── Tests ───────────────────────────────────────────────────────────────────

describe("StatusCard layout", () => {
  it("AC-4: a permission-synced source gets two cards 8 apart on LineLayout, Indexing first, Permissions Sync second", () => {
    renderCard(seedIndexed());

    const [indexing, permissions] = [indexingCard(), permissionsCard()];
    expect(
      within(indexing).getByText(copy(KEYS.title), { exact: true })
    ).toBeInTheDocument();
    expect(
      within(permissions).getByText(copy(KEYS.permissionsTitle), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(
      indexing.compareDocumentPosition(permissions) &
        Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();

    // Both cards lay out on the shared line.
    lineOf(indexing);
    lineOf(permissions);

    let parent = indexing.parentElement;
    while (parent !== null && !parent.contains(permissions)) {
      parent = parent.parentElement;
    }
    expect(parent).not.toBeNull();
    expect(parent!.style.rowGap).toBe("0.5rem");
  });

  it("AC-4: a source without permission sync gets the Indexing card only", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ["indexing", "pruning"];
    mockLatestRuns = { pruning: pruneRun() };
    renderCard(
      ccPair({
        access_type: "public",
        supports_doc_permission_sync: false,
        last_time_perm_sync: null,
        last_time_external_group_sync: null,
        last_permission_sync_attempt_status: null,
      })
    );

    expect(cards()).toHaveLength(1);
    expect(screen.queryByText(copy(KEYS.permissionsTitle))).toBeNull();
    expect(screen.queryByText(copy(KEYS.docsLabel))).toBeNull();
  });
});

describe("Indexing card column A", () => {
  it("AC-1: while indexing, A holds the label, a size-24 Indexing tag, the stage hint and the 24.23 docs/min rate", () => {
    renderCard(seedIndexing());
    const card = indexingCard();
    const { part } = lineOf(card);

    const label = within(card).getByText(copy(KEYS.title), { exact: true });
    expect(label).toHaveClass("font-secondary-action", "text-text-04");

    const tag = tagOf(card, badge("indexing"));
    expect(tag).toHaveAttribute("data-size", "6");

    const stageHint = within(card).getByRole("button", {
      name: copy(KEYS.stageHint),
    });
    const rate = within(card).getByText(
      copy(KEYS.rate).replace("{rate}", "24.23"),
      { exact: true }
    );

    const a = part(label);
    expect(part(tag)).toBe(a);
    expect(part(stageHint)).toBe(a);
    expect(part(rate)).toBe(a);
  });

  it("AC-1: an indexed pair reads Last indexed 2 minutes ago, with no stage hint and no rate", () => {
    renderCard(seedIndexed());
    const card = indexingCard();

    expect(tagOf(card, badge("indexed"))).toHaveAttribute("data-size", "6");
    expect(
      within(card).getByText(withWhen(KEYS.lastIndexed, "2 minutes ago"), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.stageHint) })
    ).toBeNull();
    expect(within(card).queryByText(/docs\/min/)).toBeNull();
  });

  it("AC-2: the latest prune and check runs show the scissors and list-check hints, each opening its run", async () => {
    const user = setupUser();
    const { onOpenRun } = renderCard(seedIndexed());
    const card = indexingCard();
    const { part } = lineOf(card);

    expect(copy(KEYS.viewPruningRun)).toBe("View Pruning Run");
    expect(copy(KEYS.viewChecksRun)).toBe("View Checks Run");

    const prune = within(card).getByRole("button", {
      name: copy(KEYS.viewPruningRun),
    });
    const checks = within(card).getByRole("button", {
      name: copy(KEYS.viewChecksRun),
    });
    expect(iconPaths(prune.querySelector("svg"))).toEqual(
      referencePaths(SvgScissors)
    );
    expect(iconPaths(checks.querySelector("svg"))).toEqual(
      referencePaths(SvgListCheck)
    );
    const a = part(within(card).getByText(copy(KEYS.title), { exact: true }));
    expect(part(prune)).toBe(a);
    expect(part(checks)).toBe(a);
    // They open another tab, not a disclosure.
    expect(prune).not.toHaveAttribute("aria-expanded");
    expect(checks).not.toHaveAttribute("aria-expanded");

    await user.click(prune);
    expect(onOpenRun).toHaveBeenLastCalledWith(PRUNE_RUN_ID, "pruning");
    await user.click(checks);
    expect(onOpenRun).toHaveBeenLastCalledWith(CHECK_RUN_ID, "checks");
    expect(onOpenRun).toHaveBeenCalledTimes(2);
  });

  it("AC-2: without a prune or check run the card shows neither hint", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {
      doc_permission_sync: docSyncRun(),
      group_sync: groupSyncRun(),
    };
    renderCard(ccPair());
    const card = indexingCard();

    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewPruningRun) })
    ).toBeNull();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewChecksRun) })
    ).toBeNull();
  });

  it("AC-2: clicking the status tag opens the latest index run", async () => {
    const user = setupUser();
    const { onOpenRun } = renderCard(seedIndexed());
    const tag = tagOf(indexingCard(), badge("indexed"));
    const button = tag.closest<HTMLElement>("button") ?? tag;

    await user.click(button);
    expect(onOpenRun).toHaveBeenCalledTimes(1);
    expect(onOpenRun).toHaveBeenCalledWith(30, "indexing");
  });

  it("AC-2: the error count is a View Errors button that focuses the errors", async () => {
    const user = setupUser();
    const { onFocusErrors, onOpenRun } = renderCard(seedIndexing());
    const card = indexingCard();

    const errors = within(card).getByRole("button", {
      name: copy(KEYS.viewErrors),
    });
    expect(errors).toHaveTextContent("3");

    await user.click(errors);
    expect(onFocusErrors).toHaveBeenCalledTimes(1);
    // The count is the latest index run's, so that run's card takes the focus.
    expect(onFocusErrors).toHaveBeenCalledWith(31);
    expect(onOpenRun).not.toHaveBeenCalled();
  });

  it("AC-1: an index run in flight that has indexed nothing yet reads Starting sync", () => {
    const pair = seedIndexing();
    mockIndexAttempts = {
      items: [
        indexAttempt({
          id: 31,
          status: "in_progress",
          total_docs_indexed: 0,
          time_started: isoAgo(MINUTE_MS),
          time_updated: isoAgo(MINUTE_MS),
          time_finished: null,
        }),
      ],
      total_items: 1,
    };
    renderCard(pair);
    const card = indexingCard();

    expect(
      within(card).getByText(copy(KEYS.startingSync), { exact: true })
    ).toBeInTheDocument();
    expect(within(card).queryByText(/^Last indexed/)).toBeNull();
    expect(within(card).queryByText(/docs\/min/)).toBeNull();
  });

  it("AC-1: a paused pair offers no prune or checks hint, since it runs nothing", () => {
    seedIndexed();
    renderCard(ccPair({ status: ConnectorCredentialPairStatus.PAUSED }), {
      panelOpen: false,
    });
    const card = indexingCard();

    expect(tagOf(card, badge("paused"))).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewPruningRun) })
    ).toBeNull();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewChecksRun) })
    ).toBeNull();
  });

  it("AC-1: a paused pair reads Paused and Last indexed 3 months ago, with no stage hint or rate", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {
      doc_permission_sync: docSyncRun({
        time_finished: isoAgo(95 * DAY_MS),
      }),
      group_sync: groupSyncRun(),
    };
    renderCard(
      ccPair({
        status: ConnectorCredentialPairStatus.PAUSED,
        last_indexed: isoAgo(95 * DAY_MS),
        last_time_perm_sync: isoAgo(95 * DAY_MS),
        last_time_external_group_sync: isoAgo(95 * DAY_MS),
      }),
      { panelOpen: false }
    );
    const card = indexingCard();

    expect(tagOf(card, badge("paused"))).toHaveAttribute("data-size", "6");
    expect(
      within(card).getByText(withWhen(KEYS.lastIndexed, "3 months ago"), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.stageHint) })
    ).toBeNull();
    expect(within(card).queryByText(/docs\/min/)).toBeNull();
    expect(
      within(card).getByText("3,248", { exact: true })
    ).toBeInTheDocument();
  });
});

describe("Indexing card queue and deletion detail", () => {
  /** A pair whose next run waits in the index queue. */
  function seedScheduled(queuePosition: number | null) {
    seedIndexed();
    mockIndexAttempts = {
      items: [
        indexAttempt({
          status: "not_started",
          time_started: null,
          time_finished: null,
        }),
      ],
      total_items: 1,
    };
    return ccPair({ queue_position: queuePosition });
  }

  /** A pair being deleted, its deletion started `startedAt` or still waiting. */
  function seedDeleting(startedAt: string | null) {
    seedIndexed();
    return ccPair({
      status: ConnectorCredentialPairStatus.DELETING,
      latest_deletion_attempt: {
        connector_id: 11,
        credential_id: 12,
        status: startedAt === null ? "PENDING" : "STARTED",
        started_at: startedAt,
      },
    });
  }

  it("a scheduled pair reads its place in the index queue", () => {
    renderCard(seedScheduled(4));
    const card = indexingCard();

    expect(tagOf(card, badge("scheduled"))).toBeInTheDocument();
    expect(
      within(card).getByText("4th in queue", { exact: true })
    ).toBeInTheDocument();
    expect(within(card).queryByText(/^Last indexed/)).toBeNull();
  });

  it("a scheduled pair without a queue place reads Last indexed", () => {
    renderCard(seedScheduled(null));
    const card = indexingCard();

    expect(tagOf(card, badge("scheduled"))).toBeInTheDocument();
    expect(
      within(card).getByText(withWhen(KEYS.lastIndexed, "2 minutes ago"), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(within(card).queryByText(/in queue/)).toBeNull();
  });

  it("a deleting pair reads when its deletion started", () => {
    renderCard(seedDeleting(isoAgo(5 * MINUTE_MS + 10_000)));
    const card = indexingCard();

    expect(tagOf(card, badge("deleting"))).toBeInTheDocument();
    expect(
      within(card).getByText(withWhen(KEYS.deletionStarted, "5 minutes ago"), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(within(card).queryByText(/^Last indexed/)).toBeNull();
  });

  it("a deleting pair whose deletion waits to start reads Last indexed", () => {
    renderCard(seedDeleting(null));
    const card = indexingCard();

    expect(tagOf(card, badge("deleting"))).toBeInTheDocument();
    expect(
      within(card).getByText(withWhen(KEYS.lastIndexed, "2 minutes ago"), {
        exact: true,
      })
    ).toBeInTheDocument();
  });
});

describe("Indexing card bars section and D", () => {
  it("AC-3: B holds 3,248 over Documents indexed, with no bar, type count, size or expand button", () => {
    renderCard(seedIndexed());
    const card = indexingCard();
    const { third, part } = lineOf(card);

    expect(copy(KEYS.indexedLabel)).toBe("Documents indexed");
    const value = within(card).getByText("3,248", { exact: true });
    const label = within(card).getByText(copy(KEYS.indexedLabel), {
      exact: true,
    });
    expect(value).toHaveClass("font-main-content-emphasis", "text-text-04");
    expect(label).toHaveClass("font-secondary-body", "text-text-03");
    expect(
      value.compareDocumentPosition(label) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();

    // Not in A with the status, and not in the third column with the panel button.
    const a = part(within(card).getByText(copy(KEYS.title), { exact: true }));
    expect(part(value)).not.toBe(a);
    expect(third).not.toContainElement(value);

    expect(within(card).queryByRole("progressbar")).toBeNull();
    expect(within(card).queryByText(/document types?/i)).toBeNull();
    expect(
      within(card).queryByText(/\b\d+(\.\d+)?\s*(KB|MB|GB|TB)\b/)
    ).toBeNull();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewDetails) })
    ).toBeNull();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.hideDetails) })
    ).toBeNull();
  });

  // The estimates follow-up stack's expand button reads View Details and Hide Details.
  it("AC-3, AC-8: the View Details and Hide Details keys land for the follow-up", () => {
    expect(copy(KEYS.viewDetails)).toBe("View Details");
    expect(copy(KEYS.hideDetails)).toBe("Hide Details");
    expect(copy(KEYS.showActivities)).toBe("Show Activities");
    expect(copy(KEYS.hideActivities)).toBe("Hide Activities");
  });

  it("AC-3: D holds only the Activities panel button, selected while the panel shows, and it calls the toggle", async () => {
    const user = setupUser();
    const { onTogglePanel } = renderCard(seedIndexed(), { panelOpen: true });
    const card = indexingCard();
    const { third } = lineOf(card);

    const button = within(card).getByRole("button", {
      name: copy(KEYS.hideActivities),
    });
    expect(third).toContainElement(button);
    expect(within(third).getAllByRole("button")).toEqual([button]);
    expect(isSelected(button)).toBe(true);

    await user.click(button);
    expect(onTogglePanel).toHaveBeenCalledTimes(1);
  });

  it("AC-3: with the panel hidden the button reads Show Activities and is not selected", async () => {
    const user = setupUser();
    const { onTogglePanel } = renderCard(seedIndexed(), { panelOpen: false });
    const card = indexingCard();

    expect(
      within(card).queryByRole("button", { name: copy(KEYS.hideActivities) })
    ).toBeNull();
    const button = within(card).getByRole("button", {
      name: copy(KEYS.showActivities),
    });
    expect(isSelected(button)).toBe(false);

    await user.click(button);
    expect(onTogglePanel).toHaveBeenCalledTimes(1);
  });

  it("AC-6: the panel button carries the page's class that hides it where the panel stacks", () => {
    render(
      <StatusCard
        ccPair={seedIndexed()}
        onStartIndexing={null}
        startingIndexing={false}
        onViewChecks={jest.fn()}
        onOpenRun={jest.fn()}
        onFocusErrors={jest.fn()}
        panelOpen
        onTogglePanel={jest.fn()}
        panelButtonClassName="hidden-when-stacked"
      />
    );
    const button = within(indexingCard()).getByRole("button", {
      name: copy(KEYS.hideActivities),
    });
    expect(button.closest(".hidden-when-stacked")).not.toBeNull();
    expect(
      indexingCard().querySelector(".hidden-when-stacked")
    ).toContainElement(button);
  });

  it("AC-3: only the Indexing card carries the panel button", () => {
    renderCard(seedIndexed());

    expect(
      within(permissionsCard()).queryByRole("button", {
        name: copy(KEYS.hideActivities),
      })
    ).toBeNull();
    expect(
      screen.getAllByRole("button", { name: copy(KEYS.hideActivities) })
    ).toHaveLength(1);
  });
});

describe("Permissions Sync card", () => {
  it("AC-4: B holds 248 over Docs permission-synced and the third column 49 over Group memberships", () => {
    renderCard(seedIndexed());
    const card = permissionsCard();
    const { third, part } = lineOf(card);

    expect(copy(KEYS.docsLabel)).toBe("Docs permission-synced");
    expect(copy(KEYS.groupsLabel)).toBe("Group memberships");

    const title = within(card).getByText(copy(KEYS.permissionsTitle), {
      exact: true,
    });
    const docs = within(card).getByText("248", { exact: true });
    const docsLabel = within(card).getByText(copy(KEYS.docsLabel), {
      exact: true,
    });
    const groups = within(card).getByText("49", { exact: true });
    const groupsLabel = within(card).getByText(copy(KEYS.groupsLabel), {
      exact: true,
    });

    expect(tagOf(card, badge("synced"))).toHaveAttribute("data-size", "6");
    expect(
      within(card).getByText(withWhen(KEYS.lastSynced, "2 minutes ago"), {
        exact: true,
      })
    ).toBeInTheDocument();

    const a = part(title);
    expect(part(docs)).not.toBe(a);
    expect(part(docs)).toBe(part(docsLabel));
    expect(third).not.toContainElement(docs);
    expect(third).toContainElement(groups);
    expect(third).toContainElement(groupsLabel);
    expect(docs).toHaveClass("font-main-content-emphasis");
    expect(groups).toHaveClass("font-main-content-emphasis");
  });

  it("AC-4: without group sync the third column is empty", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ["indexing", "doc_permission_sync", "pruning"];
    mockLatestRuns = { doc_permission_sync: docSyncRun() };
    renderCard(ccPair({ last_time_external_group_sync: null }));
    const card = permissionsCard();
    const { third } = lineOf(card);

    expect(
      within(card).getByText(copy(KEYS.docsLabel), { exact: true })
    ).toBeInTheDocument();
    expect(within(card).queryByText(copy(KEYS.groupsLabel))).toBeNull();
    expect(third.textContent?.trim() ?? "").toBe("");
  });

  it("AC-5: before the first sync the card reads Scheduled and Waiting for first index, and the tag explains docs are not searchable", async () => {
    const user = setupUser();
    mockIndexAttempts = {
      items: [
        indexAttempt({
          id: 31,
          status: "in_progress",
          time_finished: null,
        }),
      ],
      total_items: 1,
    };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {};
    renderCard(
      ccPair({
        status: ConnectorCredentialPairStatus.INITIAL_INDEXING,
        indexing: true,
        num_docs_indexed: 3248,
        last_indexed: null,
        last_time_perm_sync: null,
        last_time_external_group_sync: null,
        last_permission_sync_attempt_status: null,
        last_permission_sync_attempt_finished: null,
      })
    );
    const card = permissionsCard();

    expect(
      within(card).getByText(copy(KEYS.waitingForFirstIndex), { exact: true })
    ).toBeInTheDocument();
    const tag = tagOf(card, badge("scheduled"));
    expect(tag).toHaveAttribute("data-size", "6");

    expect(copy(KEYS.neverTooltip)).toBe(
      "Indexed docs won't be searchable until their permissions are synced."
    );
    // The badge's title carries its tooltip.
    await user.hover(
      within(tag).getByText(badge("scheduled"), { exact: false })
    );
    const tooltip = await screen.findByRole("tooltip", {}, { timeout: 3000 });
    expect(tooltip).toHaveTextContent(copy(KEYS.neverTooltip));
  });

  it("AC-5, AC-2: after a failed sync the Failed tag explains docs are not searchable and its error count focuses the errors", async () => {
    const user = setupUser();
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {
      doc_permission_sync: docSyncRun({
        status: PermissionSyncStatusEnum.FAILED,
        docs_with_permission_errors: 3,
        error_message: "Upstream connection reset",
      }),
      group_sync: groupSyncRun(),
    };
    const { onFocusErrors } = renderCard(
      ccPair({
        last_permission_sync_attempt_status: PermissionSyncStatusEnum.FAILED,
      })
    );
    const card = permissionsCard();

    const tag = tagOf(card, badge("failed"));
    expect(tag).toHaveAttribute("data-size", "6");

    const errors = within(card).getByRole("button", {
      name: copy(KEYS.viewErrors),
    });
    expect(errors).toHaveTextContent("3");
    await user.click(errors);
    expect(onFocusErrors).toHaveBeenCalledTimes(1);
    // A permission sync is no index run, so the panel shows its errors unfocused.
    expect(onFocusErrors).toHaveBeenCalledWith(null);

    // The badge's title carries its tooltip.
    await user.hover(within(tag).getByText(badge("failed"), { exact: false }));
    const tooltip = await screen.findByRole("tooltip", {}, { timeout: 3000 });
    expect(tooltip).toHaveTextContent(copy(KEYS.neverTooltip));
  });

  it("AC-5: a pair past its first index that has never synced reads Not synced yet", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {};
    renderCard(
      ccPair({
        last_time_perm_sync: null,
        last_permission_sync_attempt_status: null,
      })
    );
    const card = permissionsCard();

    expect(
      within(card).getByText(copy("admin.connector.statusCard.sync.never"), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(
      within(card).queryByText(copy(KEYS.waitingForFirstIndex))
    ).toBeNull();
  });

  it("a resolved sync keeps its error count, but not as a View Errors button, since the panel lists open runs", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    const resolved = docSyncRun({
      status: PermissionSyncStatusEnum.FAILED,
      docs_with_permission_errors: 3,
    });
    mockLatestRuns = {
      doc_permission_sync: { ...resolved, resolved_at: isoAgo(MINUTE_MS) },
      group_sync: groupSyncRun(),
    };
    renderCard(
      ccPair({
        last_permission_sync_attempt_status: PermissionSyncStatusEnum.FAILED,
      })
    );
    const card = permissionsCard();

    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewErrors) })
    ).toBeNull();
    expect(within(card).getByText("3")).toBeInTheDocument();
  });

  it("AC-5: a running sync that has synced nothing yet reads Starting sync", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {
      doc_permission_sync: docSyncRun({
        status: PermissionSyncStatusEnum.IN_PROGRESS,
        total_docs_synced: 0,
        time_started: isoAgo(MINUTE_MS),
        time_finished: null,
      }),
      group_sync: groupSyncRun(),
    };
    renderCard(
      ccPair({
        permission_syncing: true,
        last_permission_sync_attempt_status:
          PermissionSyncStatusEnum.IN_PROGRESS,
      })
    );
    const card = permissionsCard();

    expect(tagOf(card, badge("syncing"))).toHaveAttribute("data-size", "6");
    expect(
      within(card).getByText(copy(KEYS.startingSync), { exact: true })
    ).toBeInTheDocument();
    expect(within(card).queryByText(/^Last synced/)).toBeNull();
    expect(within(card).queryByText(/docs\/min/)).toBeNull();
  });

  it("AC-1: a paused pair's card reads Paused and Last synced 3 months ago and keeps its counts", () => {
    mockIndexAttempts = { items: [indexAttempt()], total_items: 1 };
    mockSourceKinds = ALL_KINDS;
    mockLatestRuns = {
      doc_permission_sync: docSyncRun({
        time_finished: isoAgo(95 * DAY_MS),
      }),
      group_sync: groupSyncRun(),
    };
    renderCard(
      ccPair({
        status: ConnectorCredentialPairStatus.PAUSED,
        last_indexed: isoAgo(95 * DAY_MS),
        last_time_perm_sync: isoAgo(95 * DAY_MS),
        last_time_external_group_sync: isoAgo(95 * DAY_MS),
      }),
      { panelOpen: false }
    );
    const card = permissionsCard();

    expect(tagOf(card, badge("paused"))).toHaveAttribute("data-size", "6");
    expect(
      within(card).getByText(withWhen(KEYS.lastSynced, "3 months ago"), {
        exact: true,
      })
    ).toBeInTheDocument();
    expect(within(card).getByText("248", { exact: true })).toBeInTheDocument();
    expect(
      within(card).getByText(copy(KEYS.docsLabel), { exact: true })
    ).toBeInTheDocument();
    expect(within(card).getByText("49", { exact: true })).toBeInTheDocument();
    expect(
      within(card).getByText(copy(KEYS.groupsLabel), { exact: true })
    ).toBeInTheDocument();
  });
});

describe("Permissions Sync card on a feed error", () => {
  it("keeps the card with the pair's last sync status and the load error, without counts", () => {
    const pair = seedIndexed();
    mockFailedKinds = ["doc_permission_sync"];
    renderCard(pair);
    const card = permissionsCard();
    tagOf(card, badge("synced"));
    expect(
      within(card).getByText(copy("admin.connector.runs.loadError.title"))
    ).toBeInTheDocument();
    expect(
      within(card).queryByText(copy(KEYS.docsLabel), { exact: true })
    ).toBeNull();
  });

  it("leaves the third column empty when only the group sync feed fails", () => {
    const pair = seedIndexed();
    mockFailedKinds = ["group_sync"];
    renderCard(pair);
    const card = permissionsCard();
    expect(
      within(card).getByText(copy(KEYS.docsLabel), { exact: true })
    ).toBeInTheDocument();
    expect(
      within(card).queryByText(copy(KEYS.groupsLabel), { exact: true })
    ).toBeNull();
  });
});

describe("StatusCard without operate", () => {
  it("AC-7: a scoped admin without operate sees the full cards, and the hints and panel button still work", async () => {
    const user = setupUser();
    const pair = seedIndexed();
    const { onOpenRun, onTogglePanel } = renderCard({
      ...pair,
      permissions: { operate: false, edit: false, delete: false },
      is_editable_for_current_user: false,
    });

    expect(cards()).toHaveLength(2);
    expect(
      within(permissionsCard()).getByText(copy(KEYS.docsLabel), {
        exact: true,
      })
    ).toBeInTheDocument();

    const prune = within(indexingCard()).getByRole("button", {
      name: copy(KEYS.viewPruningRun),
    });
    expect(prune).toBeEnabled();
    await user.click(prune);
    expect(onOpenRun).toHaveBeenCalledWith(PRUNE_RUN_ID, "pruning");

    const panelButton = within(indexingCard()).getByRole("button", {
      name: copy(KEYS.hideActivities),
    });
    expect(panelButton).toBeEnabled();
    await user.click(panelButton);
    expect(onTogglePanel).toHaveBeenCalledTimes(1);
  });
});

// ── Document types ─────────────────────────────────────────────────────────

describe("Indexing card document types", () => {
  const MB = 1024 * 1024;
  const TYPES_URL = `/api/manage/admin/cc-pair/${CC_PAIR_ID}/document-types`;
  const DOCX =
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  // Thirteen types, largest first, so the twelfth and thirteenth fold into Other.
  const MIMES: [string, string][] = [
    ["text/plain", "TXT"],
    ["image/png", "PNG"],
    ["application/pdf", "PDF"],
    [DOCX, "DOCX"],
    ["text/html", "HTML"],
    ["text/csv", "CSV"],
    ["text/markdown", "MD"],
    ["image/jpeg", "JPG"],
    ["application/json", "JSON"],
    ["application/zip", "ZIP"],
    ["image/gif", "GIF"],
    ["image/webp", "WEBP"],
    ["image/bmp", "BMP"],
  ];

  // Most cases leave `timed_out` out, which the route sends as false.
  let breakdown: Omit<CCPairDocumentTypeBreakdown, "timed_out"> & {
    timed_out?: boolean;
  };
  let typesStatus: number;

  function sized(
    mime_type: string,
    count: number,
    bytes: number
  ): DocumentTypeCount {
    return { mime_type, count, sized_count: count, size_bytes: bytes };
  }

  beforeEach(() => {
    breakdown = { types: [], untyped_count: 0 };
    typesStatus = 200;
    global.fetch = jest.fn((input: RequestInfo | URL) => {
      if (String(input) !== TYPES_URL) return new Promise<Response>(() => {});
      return Promise.resolve({
        ok: typesStatus === 200,
        status: typesStatus,
        json: async () =>
          typesStatus === 200
            ? { timed_out: false, ...breakdown }
            : { detail: "boom" },
      } as Response);
    }) as typeof fetch;
  });

  async function typesFetched() {
    await waitFor(() => expect(global.fetch).toHaveBeenCalledWith(TYPES_URL));
  }

  function typesLabel(count: number): string {
    return count === 1 ? "Document type" : "Document types";
  }

  function segments(card: HTMLElement): HTMLElement[] {
    return within(card).getAllByTestId("document-type-segment");
  }

  function cellsOf(card: HTMLElement, key: string): HTMLElement[] {
    return Array.from(
      card.querySelectorAll<HTMLElement>(`[data-document-type="${key}"]`)
    );
  }

  async function expand(card: HTMLElement) {
    const user = setupUser();
    await user.click(
      await within(card).findByRole("button", { name: copy(KEYS.viewDetails) })
    );
    return user;
  }

  it("reads the pair's document types from their own route", async () => {
    breakdown = { types: [sized("text/plain", 5, 75)], untyped_count: 0 };
    renderCard(seedIndexed());

    expect(
      await within(indexingCard()).findByText(typesLabel(1))
    ).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(TYPES_URL);
  });

  it("offers no expand button when the source reports no types", async () => {
    breakdown = { types: [], untyped_count: 5 };
    renderCard(seedIndexed());
    const card = indexingCard();

    await within(card).findByText("3,248");
    await typesFetched();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewDetails) })
    ).toBeNull();
    expect(within(card).queryByText(/Document types?/)).toBeNull();
  });

  it("a timed-out breakdown stays folded and shows no type count, as unknown rather than empty", async () => {
    breakdown = {
      types: [sized("text/plain", 5, 75)],
      untyped_count: 0,
      timed_out: true,
    };
    renderCard(seedIndexed());
    const card = indexingCard();

    await within(card).findByText("3,248");
    await typesFetched();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewDetails) })
    ).toBeNull();
    expect(within(card).queryByText(/Document types?/)).toBeNull();
  });

  it("a failed types request shows a dash and says so, rather than reading as no types", async () => {
    typesStatus = 500;
    renderCard(seedIndexed());
    const card = indexingCard();
    const { third } = lineOf(card);

    const reason = await within(card).findByText(
      copy("admin.connector.statusCard.types.loadError")
    );
    expect(third).toContainElement(reason);
    expect(third).toContainElement(within(card).getByText("—"));
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewDetails) })
    ).toBeNull();
  });

  it("a refresh that fails after a good read folds the card and shows the dash, rather than the old counts", async () => {
    jest.useFakeTimers({ advanceTimers: true });
    try {
      breakdown = { types: [sized("text/plain", 5, 75)], untyped_count: 0 };
      renderCard(seedIndexed());
      const card = indexingCard();
      await expand(card);
      expect(segments(card)).toHaveLength(1);

      typesStatus = 500;
      await act(async () => {
        jest.advanceTimersByTime(60_000);
      });

      expect(
        await within(card).findByText(
          copy("admin.connector.statusCard.types.loadError")
        )
      ).toBeInTheDocument();
      expect(within(card).getByText("—")).toBeInTheDocument();
      expect(within(card).queryByText(typesLabel(1))).toBeNull();
      expect(within(card).queryAllByTestId("document-type-segment")).toEqual(
        []
      );
    } finally {
      jest.useRealTimers();
    }
  });

  it("shows the type count but no expand button while some documents are untyped", async () => {
    breakdown = { types: [sized(DOCX, 4, 71_821)], untyped_count: 2 };
    renderCard(seedIndexed());
    const card = indexingCard();

    expect(await within(card).findByText(typesLabel(1))).toBeInTheDocument();
    expect(
      within(card).queryByRole("button", { name: copy(KEYS.viewDetails) })
    ).toBeNull();
  });

  it("folded: the type count and total size sit at the right and the expand button in D", async () => {
    breakdown = {
      types: [
        sized("text/plain", 1342, 121.5 * MB),
        sized("application/pdf", 191, 2.8 * MB),
      ],
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();
    const { third } = lineOf(card);

    const count = await within(card).findByText("2", { exact: true });
    expect(count).toHaveClass("font-main-ui-action", "text-text-03");
    expect(third).toContainElement(count);
    expect(third).toContainElement(within(card).getByText(typesLabel(2)));
    expect(within(card).getByText("124.3", { exact: true })).toHaveClass(
      "font-main-ui-action"
    );
    expect(within(card).getByText("MB", { exact: true })).toBeInTheDocument();
    expect(third).toContainElement(
      within(card).getByRole("button", { name: copy(KEYS.viewDetails) })
    );
    // Folded is never a breakdown.
    expect(within(card).queryAllByTestId("document-type-segment")).toEqual([]);
  });

  it("hides the size when any type lacks a size for some of its documents", async () => {
    breakdown = {
      types: [
        sized("text/plain", 1342, 121.5 * MB),
        { mime_type: "image/png", count: 3, sized_count: 2, size_bytes: 900 },
      ],
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();

    expect(await within(card).findByText(typesLabel(2))).toBeInTheDocument();
    expect(
      within(card).queryByText(/^(Bytes|KB|MB|GB|TB)$/, { exact: true })
    ).toBeNull();

    await expand(card);
    // The type without a full size leaves its cell blank.
    expect(within(card).getAllByText("121.5 MB").length).toBeGreaterThan(0);
    expect(within(card).queryByText(/900 Bytes/)).toBeNull();
  });

  it("unfolded: segments sort by count with the twelfth type and beyond folded into Other, always last", async () => {
    breakdown = {
      // Other (60 + 50) outnumbers the eleventh type (100), and still comes last.
      types: MIMES.map(([mime], index) =>
        sized(
          mime,
          index < 11 ? 200 - index * 10 : 60 - (index - 11) * 10,
          1000
        )
      ).reverse(),
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();

    expect(await within(card).findByText("13")).toBeInTheDocument();
    const user = await expand(card);

    const keys = segments(card).map((s) => s.dataset.documentType);
    expect(keys).toEqual([...MIMES.slice(0, 11).map(([m]) => m), "other"]);
    const expectedLabels = [...MIMES.slice(0, 11).map(([, l]) => l), "Other"];
    const wide = within(card).getByTestId("document-types-table");
    expect(
      within(wide)
        .getAllByTestId("document-type-name")
        .map((n) => n.textContent)
    ).toEqual(expectedLabels);
    // Other sums the folded types.
    expect(cellsOf(card, "other").map((c) => c.textContent)).toContain("110");

    await user.click(
      within(card).getByRole("button", { name: copy(KEYS.hideDetails) })
    );
    expect(within(card).queryAllByTestId("document-type-segment")).toEqual([]);
  });

  it("a long unmapped type name clips to its column instead of covering the counts", async () => {
    breakdown = {
      types: [sized("application/vnd.ms-excel.sheet.macroenabled.12", 3, MB)],
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();
    await expand(card);

    const wide = within(card).getByTestId("document-types-table");
    const [name] = within(wide).getAllByTestId("document-type-name");
    expect(name).toHaveTextContent("MS-EXCEL.SHEET.MACROENABLED.12");
    expect(name).toHaveClass("truncate");
    expect(name!.parentElement).toHaveClass("min-w-0", "max-w-full");
  });

  it("hovering a segment mutes every other segment and row, and hovering a row mutes the other segments", async () => {
    breakdown = {
      types: [
        sized("text/plain", 1342, 121.5 * MB),
        sized("image/png", 223, 6.3 * 1024 * MB),
        sized("application/pdf", 191, 125.3 * MB),
      ],
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();
    const user = await expand(card);

    const png = segments(card)[1]!;
    await user.hover(png);
    for (const cell of cellsOf(card, "image/png")) {
      expect(cell).not.toHaveClass("opacity-50");
    }
    for (const key of ["text/plain", "application/pdf"]) {
      for (const cell of cellsOf(card, key)) {
        expect(cell).toHaveClass("opacity-50");
      }
    }

    await user.unhover(png);
    for (const cell of cellsOf(card, "text/plain")) {
      expect(cell).not.toHaveClass("opacity-50");
    }

    const pdfName = within(
      within(card).getByTestId("document-types-table")
    ).getByText("PDF");
    await user.hover(pdfName);
    expect(segments(card)[2]).not.toHaveClass("opacity-50");
    expect(segments(card)[0]).toHaveClass("opacity-50");
    expect(segments(card)[1]).toHaveClass("opacity-50");
  });

  it("folding while a type is hovered clears the mute, so the next unfold shows every type", async () => {
    breakdown = {
      types: [
        sized("text/plain", 1342, 121.5 * MB),
        sized("image/png", 223, 6.3 * 1024 * MB),
      ],
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();
    const user = await expand(card);

    await user.hover(segments(card)[1]!);
    expect(segments(card)[0]).toHaveClass("opacity-50");
    // The keyboard folds and unfolds while the pointer still rests where the segment was, so no leave fires.
    within(card)
      .getByRole("button", { name: copy(KEYS.hideDetails) })
      .focus();
    await user.keyboard("{Enter}");
    within(card)
      .getByRole("button", { name: copy(KEYS.viewDetails) })
      .focus();
    await user.keyboard("{Enter}");

    for (const segment of segments(card)) {
      expect(segment).not.toHaveClass("opacity-50");
    }
  });

  it("a refresh that folds the card while a type is hovered clears the mute, so the table comes back with every type", async () => {
    jest.useFakeTimers({ advanceTimers: true });
    try {
      const full = {
        types: [
          sized("text/plain", 1342, 121.5 * MB),
          sized("image/png", 223, 6.3 * 1024 * MB),
        ],
        untyped_count: 0,
      };
      breakdown = full;
      renderCard(seedIndexed());
      const card = indexingCard();
      const user = await expand(card);
      await user.hover(segments(card)[1]!);
      expect(segments(card)[0]).toHaveClass("opacity-50");

      breakdown = { ...full, timed_out: true };
      await act(async () => {
        jest.advanceTimersByTime(60_000);
      });
      await waitFor(() =>
        expect(within(card).queryAllByTestId("document-type-segment")).toEqual(
          []
        )
      );

      breakdown = full;
      await act(async () => {
        jest.advanceTimersByTime(60_000);
      });
      await waitFor(() => expect(segments(card)).toHaveLength(2));
      for (const segment of segments(card)) {
        expect(segment).not.toHaveClass("opacity-50");
      }
    } finally {
      jest.useRealTimers();
    }
  });

  it("below 640 px each type takes two lines, name then count and size, with no headers and rows ending 32 px inside the line", async () => {
    breakdown = {
      types: [
        sized("text/plain", 1342, 121.5 * MB),
        sized("image/png", 223, 6.3 * 1024 * MB),
      ],
      untyped_count: 0,
    };
    renderCard(seedIndexed());
    const card = indexingCard();
    await expand(card);

    const wide = within(card).getByTestId("document-types-table");
    const narrow = within(card).getByTestId("document-types-list");
    expect(wide).toHaveClass("@max-[38.75rem]:hidden");
    expect(narrow).toHaveClass("hidden", "@max-[38.75rem]:flex");
    expect(within(narrow).queryByText("Indexed")).toBeNull();
    expect(within(narrow).queryByText("Size")).toBeNull();

    const items = within(narrow).getAllByTestId("document-type-item");
    expect(items).toHaveLength(2);
    const [name, figures] = [
      within(items[0]!).getByText("TXT"),
      within(items[0]!).getByText("1,342 (121.5 MB)"),
    ];
    expect(
      name.compareDocumentPosition(figures) & Node.DOCUMENT_POSITION_FOLLOWING
    ).toBeTruthy();
    for (const item of items) expect(item).toHaveClass("me-6");
  });

  it("below 640 px a card that can unfold keeps its bar row folded, so unfolding never moves the count", async () => {
    breakdown = { types: [sized("text/plain", 5, 75)], untyped_count: 0 };
    renderCard(seedIndexed());
    const card = indexingCard();
    await within(card).findByRole("button", { name: copy(KEYS.viewDetails) });

    // The open bar is a 20 px line and a 4 px gap above the count, so the folded count and summary hold the same 24 px.
    const figure = within(card).getByText("3,248", { exact: true });
    const summary = within(card).getByText(typesLabel(1));
    for (const part of [figure, summary]) {
      const held = part.closest(".mt-6");
      expect(held).not.toBeNull();
      expect(held).not.toHaveClass("@max-[38.75rem]:mt-0");
    }
  });

  it("below 640 px a card that cannot unfold drops the bar row, so the wrapped count sits under column A", async () => {
    breakdown = { types: [sized(DOCX, 4, 71_821)], untyped_count: 2 };
    renderCard(seedIndexed());
    const card = indexingCard();
    const summary = await within(card).findByText(typesLabel(1));

    const figure = within(card).getByText("3,248", { exact: true });
    for (const part of [figure, summary]) {
      expect(part.closest(".mt-6")).toHaveClass("@max-[38.75rem]:mt-0");
    }
  });
});
