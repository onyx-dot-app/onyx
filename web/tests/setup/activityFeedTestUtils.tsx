/** A fake of the activity feed routes with the backend's filter semantics, so tests pin what the panel shows and sends, not its queries. */
import { render } from "@tests/setup/test-utils";
import type { IconFunctionComponent } from "@opal/types";
import type {
  CCPairRun,
  CCPairRunKind,
  CCPairRunStatusGroup,
} from "@/lib/connectors/types";
import type { ValidSources } from "@/lib/connectors/types/source";
import type { ValidStatuses } from "@/lib/types";

type StatusGroup = CCPairRunStatusGroup | "scheduled";

/** One run in the fake feed, with the facts the backend filters on. */
export interface FeedRun {
  ccPairId: number;
  run: CCPairRun;
  group: StatusGroup;
  /** Open document or item errors, errors all closed, or none recorded. */
  errors: "open" | "closed" | "none";
  resolved: boolean;
  superseded: boolean;
}

export interface FeedPair {
  id: number;
  name: string;
  source: ValidSources;
  can_resolve: boolean;
  can_resolve_runs: boolean;
}

export const SALES_DRIVE: FeedPair = {
  id: 7,
  name: "Sales Drive",
  source: "google_drive" as ValidSources,
  can_resolve: true,
  can_resolve_runs: true,
};

export const SUPPORT_INBOX: FeedPair = {
  id: 8,
  name: "Support Inbox",
  source: "gmail" as ValidSources,
  can_resolve: true,
  can_resolve_runs: true,
};

/** A pair the viewer may read but not operate. */
export const READ_ONLY_WIKI: FeedPair = {
  id: 9,
  name: "Read Only Wiki",
  source: "confluence" as ValidSources,
  can_resolve: false,
  can_resolve_runs: false,
};

const NOW = Date.now();

export function minutesAgo(minutes: number): string {
  return new Date(NOW - minutes * 60_000).toISOString();
}

function closure(minutes: number, resolved: boolean, superseded: boolean) {
  return {
    resolved_at: resolved ? minutesAgo(Math.max(minutes - 1, 0)) : null,
    superseded,
  };
}

function indexGroup(status: ValidStatuses): StatusGroup {
  switch (status) {
    case "failed":
    case "invalid":
      return "failed";
    case "in_progress":
      return "running";
    case "not_started":
      return "scheduled";
    case "canceled":
    case "interrupted":
      return "canceled";
    case "success":
    case "completed_with_errors":
      return "succeeded";
  }
}

export interface IndexRunOptions {
  id: number;
  status: ValidStatuses;
  minutesAgo: number;
  ccPairId?: number;
  /** Every error the run filed, resolved ones included. */
  errorCount?: number;
  openErrors?: number;
  openDocErrors?: number;
  errorMsg?: string | null;
  trace?: string | null;
  resolved?: boolean;
  superseded?: boolean;
}

export function indexRun(options: IndexRunOptions): FeedRun {
  const {
    id,
    status,
    ccPairId = SALES_DRIVE.id,
    openErrors = 0,
    errorMsg = null,
    trace = null,
    resolved = false,
    superseded = false,
  } = options;
  const errorCount = options.errorCount ?? openErrors;
  const openDocErrors = options.openDocErrors ?? openErrors;
  const created = minutesAgo(options.minutesAgo);
  const finished = status !== "in_progress" && status !== "not_started";
  return {
    ccPairId,
    group: indexGroup(status),
    errors: openErrors > 0 ? "open" : errorCount > 0 ? "closed" : "none",
    resolved,
    superseded,
    run: {
      kind: "indexing",
      time_created: created,
      ...closure(options.minutesAgo, resolved, superseded),
      attempt: {
        id,
        status,
        from_beginning: false,
        new_docs_indexed: 125,
        docs_removed_from_index: 0,
        total_docs_indexed: 125,
        error_msg: errorMsg,
        error_count: errorCount,
        open_error_count: openErrors,
        open_doc_error_count: openDocErrors,
        full_exception_trace: trace,
        time_started: status === "not_started" ? null : created,
        time_updated: created,
        time_finished: finished
          ? minutesAgo(Math.max(options.minutesAgo - 5, 0))
          : null,
        is_new_model: false,
        is_backfill: false,
      },
    },
  };
}

function syncGroup(status: string): StatusGroup {
  switch (status) {
    case "failed":
      return "failed";
    case "in_progress":
      return "running";
    case "not_started":
      return "scheduled";
    case "canceled":
      return "canceled";
    default:
      return "succeeded";
  }
}

export interface SyncRunOptions {
  id: number;
  status: "success" | "completed_with_errors" | "failed" | "in_progress";
  minutesAgo: number;
  ccPairId?: number;
  errorMessage?: string | null;
  trace?: string | null;
}

/** A permission sync. Its unreadable documents count as open errors, as the backend's `errors` axis reads them. */
export function permSyncRun(
  options: SyncRunOptions & { docsWithPermissionErrors: number }
): FeedRun {
  const created = minutesAgo(options.minutesAgo);
  return {
    ccPairId: options.ccPairId ?? SALES_DRIVE.id,
    group: syncGroup(options.status),
    errors: options.docsWithPermissionErrors > 0 ? "open" : "none",
    resolved: false,
    superseded: false,
    run: {
      kind: "doc_permission_sync",
      time_created: created,
      ...closure(options.minutesAgo, false, false),
      attempt: {
        id: options.id,
        status: options.status as never,
        error_message: options.errorMessage ?? null,
        full_exception_trace: options.trace ?? null,
        total_docs_synced: 125,
        docs_with_permission_errors: options.docsWithPermissionErrors,
        time_created: created,
        time_started: created,
        time_finished: minutesAgo(Math.max(options.minutesAgo - 5, 0)),
      },
    },
  };
}

/** A group sync. Its failed users and groups count every row, resolved ones included; `openErrors` counts the open ones. */
export function groupSyncRun(
  options: SyncRunOptions & {
    failedUsers?: number;
    failedGroups?: number;
    openErrors?: number;
  }
): FeedRun {
  const { failedUsers = 0, failedGroups = 0, openErrors = 0 } = options;
  const created = minutesAgo(options.minutesAgo);
  return {
    ccPairId: options.ccPairId ?? SALES_DRIVE.id,
    group: syncGroup(options.status),
    errors:
      openErrors > 0
        ? "open"
        : failedUsers + failedGroups > 0
          ? "closed"
          : "none",
    resolved: false,
    superseded: false,
    run: {
      kind: "group_sync",
      time_created: created,
      ...closure(options.minutesAgo, false, false),
      attempt: {
        id: options.id,
        status: options.status as never,
        error_message: options.errorMessage ?? null,
        full_exception_trace: options.trace ?? null,
        total_users_processed: 40,
        total_groups_processed: 6,
        total_group_memberships_synced: 80,
        failed_users: failedUsers,
        failed_groups: failedGroups,
        open_error_count: openErrors,
        time_created: created,
        time_started: created,
        time_finished: minutesAgo(Math.max(options.minutesAgo - 5, 0)),
      },
    },
  };
}

function failedCheck(index: number) {
  return {
    capability: "doc_permission_sync",
    check_id: `check_${index}`,
    display_name: `Check ${index}`,
    required: true,
    status: "failed",
    message: "No read access for linked pages.",
    summary: "No read access for linked pages.",
    description: null,
    error_kind: null,
    not_run_reason: null,
    applicable: true,
    remediation: null,
    docs_link: null,
    duration_ms: 10,
    findings: [],
  };
}

/** A failed check run with `failedChecks` required checks failed. Checks record no per-item errors. */
export function failedChecksRun(options: {
  id: number;
  minutesAgo: number;
  failedChecks: number;
  ccPairId?: number;
}): FeedRun {
  const created = minutesAgo(options.minutesAgo);
  return {
    ccPairId: options.ccPairId ?? SALES_DRIVE.id,
    group: "failed",
    errors: "none",
    resolved: false,
    superseded: false,
    run: {
      kind: "checks",
      time_created: created,
      ...closure(options.minutesAgo, false, false),
      attempt: {
        id: options.id,
        status: "failed",
        trigger: "manual",
        check_results: Array.from({ length: options.failedChecks }, (_, i) =>
          failedCheck(i)
        ) as never,
        error_message: null,
        time_created: created,
        time_started: created,
        time_finished: minutesAgo(Math.max(options.minutesAgo - 1, 0)),
      },
    },
  };
}

/** The key a card carries in `data-run-key`. */
export function runKey(feedRun: FeedRun): string {
  return `${feedRun.run.kind}-${feedRun.run.attempt.id}`;
}

function messagesOf(feedRun: FeedRun): string[] {
  const run = feedRun.run;
  const own =
    run.kind === "indexing" ? run.attempt.error_msg : run.attempt.error_message;
  return own === null ? [] : [own];
}

const ACTIVE: StatusGroup[] = ["running", "scheduled"];

interface MatchOptions {
  ccPairId: number | null;
  ignoreStatus?: boolean;
}

/** The backend's `CCPairRunFilter` over the pool: `errors` and a true closure axis widen each other, a false one narrows. */
function matches(
  feedRun: FeedRun,
  params: URLSearchParams,
  { ccPairId, ignoreStatus = false }: MatchOptions
): boolean {
  if (ccPairId !== null && feedRun.ccPairId !== ccPairId) return false;
  const ids = params.getAll("cc_pair_ids").map(Number);
  if (ids.length > 0 && !ids.includes(feedRun.ccPairId)) return false;
  const kinds = params.getAll("kinds");
  if (kinds.length > 0 && !kinds.includes(feedRun.run.kind)) return false;
  const groups = params.getAll("status_groups");
  if (!ignoreStatus && groups.length > 0 && !groups.includes(feedRun.group)) {
    return false;
  }
  const widened: boolean[] = [];
  const errors = params.get("errors");
  if (errors === "unresolved") widened.push(feedRun.errors === "open");
  if (errors === "resolved") widened.push(feedRun.errors === "closed");
  if (errors === "none") widened.push(feedRun.errors === "none");
  const superseded = params.get("superseded");
  const resolved = params.get("resolved");
  if (superseded === "true") widened.push(feedRun.superseded);
  if (resolved === "true") widened.push(feedRun.resolved);
  if (widened.length > 0 && !widened.some(Boolean)) return false;
  if (superseded === "false" && feedRun.superseded) return false;
  if (resolved === "false" && feedRun.resolved) return false;
  const created = Date.parse(feedRun.run.time_created);
  const active = ACTIVE.includes(feedRun.group);
  const since = params.get("since");
  const until = params.get("until");
  if (since !== null && created < Date.parse(since) && !active) return false;
  if (until !== null && created >= Date.parse(until) && !active) return false;
  const q = params.get("q")?.trim().toLowerCase();
  if (q && !messagesOf(feedRun).some((m) => m.toLowerCase().includes(q))) {
    return false;
  }
  return true;
}

/** `open_level_filters`: what `resolvable-count` counts and the batch resolves mark. A `status_groups` narrows each level's own groups. */
function resolvable(
  feedRun: FeedRun,
  params: URLSearchParams,
  ccPairId: number | null
) {
  const level = params.get("level");
  const q = params.get("q")?.trim();
  const requested = params.getAll("status_groups");
  const levels = level === null ? ["failures", "errors"] : [level];
  return levels.some((candidate) => {
    const levelParams = new URLSearchParams(params);
    levelParams.delete("level");
    levelParams.delete("status_groups");
    levelParams.set("resolved", "false");
    if (!q) levelParams.set("superseded", "false");
    const levelGroups =
      candidate === "failures"
        ? ["failed"]
        : ["running", "succeeded", "canceled"];
    if (candidate !== "failures") levelParams.set("errors", "unresolved");
    const groups = levelGroups.filter(
      (group) => requested.length === 0 || requested.includes(group)
    );
    if (groups.length === 0) return false;
    groups.forEach((group) => levelParams.append("status_groups", group));
    return matches(feedRun, levelParams, { ccPairId });
  });
}

function bodyParams(body: Record<string, unknown>): URLSearchParams {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(body)) {
    if (value === null || value === undefined || value === "") continue;
    if (Array.isArray(value)) {
      value.forEach((item) => params.append(key, String(item)));
    } else {
      params.set(key, String(value));
    }
  }
  return params;
}

export interface FeedRequest {
  method: string;
  url: URL;
  body: Record<string, unknown> | null;
}

export interface ActivityFeed {
  requests: FeedRequest[];
  /** Requests whose path ends with `pathSuffix`, of `method`. */
  calls(method: string, pathSuffix: string): FeedRequest[];
}

const ALL_KINDS: CCPairRunKind[] = [
  "indexing",
  "doc_permission_sync",
  "group_sync",
  "pruning",
  "checks",
];
const GROUPS: StatusGroup[] = [
  "running",
  "scheduled",
  "succeeded",
  "failed",
  "canceled",
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function connectorRow(pair: FeedPair) {
  return {
    cc_pair_id: pair.id,
    name: pair.name,
    source: pair.source,
    access_type: "public",
    cc_pair_status: "ACTIVE",
    status: "indexed",
    creator_email: null,
    creator_name: null,
    docs_indexed: 125,
    last_success: null,
    latest_index_attempt: null,
    open_error_count: 0,
    queue_position: null,
    permissions: { operate: true, read: true, admin: true },
  };
}

let originalFetch: typeof fetch | undefined;

/** Serves the pool through `fetch` until `restoreFetch`. Unknown routes answer 404. */
export function installActivityFeed(
  pool: FeedRun[],
  pairs: FeedPair[] = [SALES_DRIVE, SUPPORT_INBOX, READ_ONLY_WIKI]
): ActivityFeed {
  const requests: FeedRequest[] = [];
  const newestFirst = [...pool].sort(
    (a, b) =>
      Date.parse(b.run.time_created) - Date.parse(a.run.time_created) ||
      b.run.attempt.id - a.run.attempt.id
  );
  const pairOf = (id: number) => pairs.find((pair) => pair.id === id)!;

  function feed(params: URLSearchParams, ccPairId: number | null) {
    const matching = newestFirst.filter((run) =>
      matches(run, params, { ccPairId })
    );
    const pageNum = Number(params.get("page_num") ?? 0);
    const pageSize = Number(params.get("page_size") ?? 10);
    const page = matching.slice(pageNum * pageSize, (pageNum + 1) * pageSize);
    const statusCounts = Object.fromEntries(
      GROUPS.map((group) => [
        group,
        newestFirst.filter(
          (run) =>
            run.group === group &&
            matches(run, params, { ccPairId, ignoreStatus: true })
        ).length,
      ])
    );
    return {
      items: page.map((run) =>
        ccPairId === null
          ? { cc_pair: pairOf(run.ccPairId), run: run.run }
          : run.run
      ),
      total_items: matching.length,
      kinds: ALL_KINDS,
      status_counts: statusCounts,
    };
  }

  function count(params: URLSearchParams, ccPairId: number | null) {
    return newestFirst.filter((run) => resolvable(run, params, ccPairId))
      .length;
  }

  originalFetch = global.fetch;
  global.fetch = jest.fn(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const raw =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      const url = new URL(raw, "http://localhost");
      const method = (init?.method ?? "GET").toUpperCase();
      const body =
        typeof init?.body === "string"
          ? (JSON.parse(init.body) as Record<string, unknown>)
          : null;
      requests.push({ method, url, body });
      const path = url.pathname;
      const pair = /^\/api\/manage\/admin\/cc-pair\/(\d+)\/(.+)$/.exec(path);
      const pairId = pair === null ? null : Number(pair[1]);
      const rest = pair?.[2] ?? null;
      const fleet = path.startsWith("/api/manage/admin/index-monitoring/");

      if (method === "GET") {
        if (rest === "runs") return json(feed(url.searchParams, pairId));
        if (path === "/api/manage/admin/index-monitoring/runs") {
          return json(feed(url.searchParams, null));
        }
        if (rest === "runs/resolvable-count") {
          return json({ count: count(url.searchParams, pairId) });
        }
        if (fleet && path.endsWith("/runs/resolvable-count")) {
          return json({ count: count(url.searchParams, null) });
        }
        if (path === "/api/manage/admin/index-monitoring/connectors") {
          const q = url.searchParams.get("q")?.toLowerCase() ?? "";
          const rows = pairs
            .filter((candidate) => candidate.name.toLowerCase().includes(q))
            .map(connectorRow);
          return json({
            items: rows,
            total_items: rows.length,
            status_counts: { indexed: rows.length },
            source_counts: {},
            federated_connectors: [],
          });
        }
        if (rest === "errors") return json({ items: [], total_items: 0 });
      }
      if (method === "POST") {
        if (rest === "runs/resolve") {
          const runs = (body?.runs as unknown[] | undefined) ?? [];
          return json({ resolved_count: runs.length });
        }
        if (rest === "errors/resolve") {
          const ids = (body?.error_ids as unknown[] | undefined) ?? [];
          return json({ resolved_count: ids.length });
        }
        if (rest === "runs/resolve-matching") {
          const resolved = count(bodyParams(body ?? {}), pairId);
          return json({
            resolved_count: resolved,
            cc_pair_ids: resolved > 0 ? [pairId] : [],
          });
        }
        if (path === "/api/manage/admin/index-monitoring/runs/resolve") {
          const params = bodyParams(body ?? {});
          const marked = newestFirst.filter((run) =>
            resolvable(run, params, null)
          );
          return json({
            resolved_count: marked.length,
            cc_pair_ids: Array.from(new Set(marked.map((run) => run.ccPairId))),
          });
        }
      }
      return json({ detail: `No fake for ${method} ${path}` }, 404);
    }
  ) as typeof fetch;

  return {
    requests,
    calls: (method, pathSuffix) =>
      requests.filter(
        (request) =>
          request.method === method && request.url.pathname.endsWith(pathSuffix)
      ),
  };
}

export function restoreFetch() {
  if (originalFetch !== undefined) global.fetch = originalFetch;
  originalFetch = undefined;
}

// ── DOM helpers ────────────────────────────────────────────────────────────

/** The panel's cards in DOM order, by `data-run-key`. */
export function cardKeys(root: ParentNode = document): string[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>('[data-testid="activity-card"]')
  ).map((card) => card.getAttribute("data-run-key") ?? "");
}

export function cardFor(feedRun: FeedRun): HTMLElement | null {
  return document.querySelector<HTMLElement>(
    `[data-testid="activity-card"][data-run-key="${runKey(feedRun)}"]`
  );
}

export interface ShownSection {
  title: string;
  keys: string[];
}

/** The panel's sections in DOM order: each heading and the cards under it. */
export function shownSections(root: ParentNode = document): ShownSection[] {
  return Array.from(
    root.querySelectorAll<HTMLElement>('[data-testid="activity-section"]')
  ).map((section) => ({
    title: (
      section.querySelector('[data-testid="activity-section-title"]')
        ?.textContent ?? ""
    )
      .replace(/\s+/g, " ")
      .trim(),
    keys: cardKeys(section),
  }));
}

function iconPaths(svg: Element): string[] {
  return Array.from(svg.querySelectorAll("path")).map(
    (path) => path.getAttribute("d") ?? ""
  );
}

/** The path data an icon draws, to find it in rendered markup. */
export function referencePaths(Icon: IconFunctionComponent): string[] {
  const { container, unmount } = render(<Icon size={16} />);
  const paths = iconPaths(container.querySelector("svg")!);
  unmount();
  return paths;
}

/** Whether `root` holds an svg drawing exactly `paths`. */
export function holdsIcon(root: Element, paths: string[]): boolean {
  return Array.from(root.querySelectorAll("svg")).some(
    (svg) => JSON.stringify(iconPaths(svg)) === JSON.stringify(paths)
  );
}
