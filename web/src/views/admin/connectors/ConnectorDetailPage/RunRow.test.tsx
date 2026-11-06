/** A run line on LineLayout, with a size-20 spinner tag, text-02 run-type icon and the SvgDocFile View Logs. */
import { render, screen, setupUser, within } from "@tests/setup/test-utils";
import {
  SvgAlertTriangle,
  SvgDocFile,
  SvgFileText,
  SvgRefreshCw,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import {
  PermissionSyncStatusEnum,
  type CCPairRun,
} from "@/lib/connectors/types";
import { formatDateTimeLog } from "@/lib/dateUtils";
import englishMessages from "@/i18n/messages/en.json";
import RunRow from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

// A line under 620 px, which is a card under 640 px once its border and padding are taken off.
const BELOW_640 = String.raw`@max-\[(?:38\.75rem|620px)\]:`;

const NOW = new Date().toISOString();

// A running index attempt that already logged an error, so Cancel and View Logs both show.
const RUN: CCPairRun = {
  kind: "indexing",
  time_created: NOW,
  resolved_at: null,
  superseded: false,
  attempt: {
    id: 21,
    status: "in_progress",
    from_beginning: false,
    new_docs_indexed: 100,
    docs_removed_from_index: 0,
    total_docs_indexed: 125,
    error_msg: "Connector timed out",
    error_count: 0,
    open_error_count: 0,
    open_doc_error_count: 0,
    full_exception_trace: null,
    time_started: NOW,
    time_updated: NOW,
    time_finished: null,
    is_new_model: false,
    is_backfill: false,
  },
};

function renderRun() {
  return render(
    <RunRow
      run={RUN}
      canCancel
      onCancel={jest.fn()}
      onViewLogs={jest.fn()}
      open={false}
      onOpenChange={jest.fn()}
      dimmed={false}
    />
  );
}

function hasClass(element: Element, pattern: string): boolean {
  const re = new RegExp(`^${pattern}$`);
  return Array.from(element.classList).some((name) => re.test(name));
}

/** Classes that would lay the subtree out as a CSS grid. */
function gridClasses(root: Element): string[] {
  return [root, ...Array.from(root.querySelectorAll("*"))]
    .flatMap((element) => Array.from(element.classList))
    .filter((name) => /(^|:)(inline-)?grid($|-)/.test(name));
}

function iconPaths(svg: Element): string[] {
  return Array.from(svg.querySelectorAll("path")).map(
    (path) => path.getAttribute("d") ?? ""
  );
}

function referencePaths(Icon: IconFunctionComponent): string[] {
  const { container, unmount } = render(<Icon size={16} />);
  const paths = iconPaths(container.querySelector("svg")!);
  unmount();
  return paths;
}

/** The first svg inside the closest self-or-ancestor of `element` that holds one. */
function nearestIcon(element: HTMLElement): SVGElement {
  let current: HTMLElement | null = element;
  while (current !== null && current.querySelector("svg") === null) {
    current = current.parentElement;
  }
  return current!.querySelector("svg")!;
}

function lineParts(container: HTMLElement) {
  const third = container.querySelector<HTMLElement>(".basis-1\\/3");
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
  return { root, third: third!, part };
}

describe("RunRow on LineLayout", () => {
  it("AC-1, D-1: puts the type in A, the status in B, the counts in C and the actions in D, with no grid", () => {
    const { container } = renderRun();
    const { root, third, part } = lineParts(container);

    const a = part(screen.getByText("Document Index"));
    const b = part(screen.getByText("Indexing"));
    const c = part(screen.getByText("indexed"));
    const d = part(screen.getByRole("button", { name: "View Logs" }));

    expect(a.parentElement).toBe(root);
    expect(a).toHaveClass("flex-1", "min-w-0");
    expect(b.parentElement).toBe(root);
    expect(b).toHaveClass("flex-1", "min-w-0");
    expect(a).not.toBe(b);
    expect(c.parentElement).toBe(third);
    expect(c).toHaveClass("flex-1", "min-w-0");
    expect(d.parentElement).toBe(third);
    expect(d).toHaveClass("w-16", "shrink-0");
    expect(part(screen.getByRole("button", { name: "Cancel" }))).toBe(d);
    expect(gridClasses(container)).toEqual([]);
  });

  it("AC-2: gives a run line's actions the 90 px floor below 640 px", () => {
    const { container } = renderRun();
    const { part } = lineParts(container);

    const d = part(screen.getByRole("button", { name: "View Logs" }));
    expect(hasClass(d, `${BELOW_640}min-w-\\[(?:90px|5\\.625rem)\\]`)).toBe(
      true
    );
  });

  it("AC-1: sits under a container query root inside the run line", () => {
    const { container } = renderRun();
    const { root } = lineParts(container);

    const queryRoot = root.closest('[class~="@container"]');
    expect(queryRoot).not.toBeNull();
    expect(container.contains(queryRoot)).toBe(true);
  });

  it("AC-3: View Logs uses SvgDocFile, not SvgAlertTriangle or SvgFileText", () => {
    const docFile = referencePaths(SvgDocFile);
    const alert = referencePaths(SvgAlertTriangle);
    const fileText = referencePaths(SvgFileText);
    renderRun();

    const button = screen.getByRole("button", { name: "View Logs" });
    const glyph = iconPaths(button.querySelector("svg")!);
    expect(glyph).toEqual(docFile);
    expect(glyph).not.toEqual(alert);
    expect(glyph).not.toEqual(fileText);
  });

  it("AC-4, AC-5: tags a running run at size 20 with the Opal spinner", () => {
    renderRun();

    const tag = screen.getByText("Indexing").closest(".opal-badge");
    expect(tag).toHaveAttribute("data-size", "5");
    expect(tag!.querySelector('svg[role="status"]')).not.toBeNull();
  });

  it("AC-5: colors the run-type icon text-02", () => {
    renderRun();

    expect(nearestIcon(screen.getByText("Document Index"))).toHaveClass(
      "stroke-text-02"
    );
  });
});

// Run-line content. Copy comes from the English catalog by key, so a missing key fails as missing copy.

const MINUTE_MS = 60_000;
// A fixed past start, so a finished run's figures do not depend on the clock.
const START = "2026-03-23T10:00:00.000Z";

function isoAfter(iso: string, ms: number): string {
  return new Date(new Date(iso).getTime() + ms).toISOString();
}

/** The English message at `path` with `{name}` placeholders filled in. A missing key fails the test. */
function copy(path: string, values: Record<string, string> = {}): string {
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
  return Object.entries(values).reduce(
    (text, [name, value]) => text.replace(`{${name}}`, value),
    raw as string
  );
}

type IndexRun = Extract<CCPairRun, { kind: "indexing" }>;
type IndexAttempt = IndexRun["attempt"];

function indexRun(
  attempt: Partial<IndexAttempt> = {},
  run: Partial<Omit<IndexRun, "kind" | "attempt">> & { is_retry?: boolean } = {}
): CCPairRun {
  return {
    kind: "indexing",
    time_created: START,
    resolved_at: null,
    superseded: false,
    is_retry: false,
    ...run,
    attempt: {
      id: 31,
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
      time_started: START,
      time_updated: isoAfter(START, 5 * MINUTE_MS),
      time_finished: isoAfter(START, 5 * MINUTE_MS),
      is_new_model: false,
      is_backfill: false,
      ...attempt,
    },
  } as CCPairRun;
}

/** An index attempt that is running now, started `minutes` ago. */
function runningAttempt(minutes: number): Partial<IndexAttempt> {
  const now = Date.now();
  return {
    status: "in_progress",
    time_started: new Date(now - minutes * MINUTE_MS).toISOString(),
    time_updated: new Date(now).toISOString(),
    time_finished: null,
  };
}

function groupSyncRun(
  attempt: Partial<Extract<CCPairRun, { kind: "group_sync" }>["attempt"]>
): CCPairRun {
  return {
    kind: "group_sync",
    time_created: START,
    resolved_at: null,
    superseded: false,
    attempt: {
      id: 41,
      status: PermissionSyncStatusEnum.SUCCESS,
      error_message: null,
      full_exception_trace: null,
      total_users_processed: 122,
      total_groups_processed: 3,
      total_group_memberships_synced: 125,
      failed_users: 0,
      failed_groups: 0,
      open_error_count: 0,
      time_created: START,
      time_started: START,
      time_finished: isoAfter(START, 5 * MINUTE_MS),
      ...attempt,
    },
  };
}

function renderLine(run: CCPairRun, canCancel = true) {
  const onCancel = jest.fn();
  const view = render(
    <RunRow
      run={run}
      canCancel={canCancel}
      onCancel={onCancel}
      onViewLogs={jest.fn()}
      open={false}
      onOpenChange={jest.fn()}
      dimmed={false}
    />
  );
  return { ...view, onCancel };
}

/** `element` and its ancestors up to `root`, nearest first. */
function selfAndAncestors(element: Element, root: Element): Element[] {
  const chain: Element[] = [];
  let current: Element | null = element;
  while (current !== null && current !== root.parentElement) {
    chain.push(current);
    current = current.parentElement;
  }
  return chain;
}

function classesOf(elements: Element[]): string[] {
  return elements.flatMap((element) => Array.from(element.classList));
}

function nearestCommonAncestor(first: Element, second: Element): Element {
  let current: Element | null = first;
  while (current !== null && !current.contains(second)) {
    current = current.parentElement;
  }
  return current!;
}

describe("RunRow run-line content (FE-7)", () => {
  it("AC-2: reads Starting sync before a running or queued index run has a rate, then the live rate", () => {
    const starting = copy("admin.connector.runs.detail.starting");

    const { unmount } = renderLine(
      indexRun({
        ...runningAttempt(1),
        total_docs_indexed: 0,
        new_docs_indexed: 0,
      })
    );
    expect(screen.getByText(starting)).toBeInTheDocument();
    unmount();

    const queued = renderLine(
      indexRun({
        status: "not_started",
        time_started: null,
        time_finished: null,
        total_docs_indexed: 0,
        new_docs_indexed: 0,
      })
    );
    expect(screen.getByText(starting)).toBeInTheDocument();
    queued.unmount();

    // 125 docs over the 5 minutes since it started: 25.00 docs/min.
    renderLine(indexRun(runningAttempt(5)));
    expect(
      screen.getByText(
        copy("admin.connector.runs.detail.rate", { rate: "25.00" })
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(starting)).toBeNull();
  });

  it("AC-2: reads rate (duration) when a finished run indexed docs, as 25.00 docs/min (5 min)", () => {
    renderLine(indexRun());

    expect(
      screen.getByText(
        copy("admin.connector.runs.detail.rateFinished", {
          rate: "25.00",
          duration: "5 min",
        })
      )
    ).toBeInTheDocument();
  });

  it("AC-2: reads Runtime {duration} when a finished run indexed nothing", () => {
    renderLine(
      indexRun({
        total_docs_indexed: 0,
        new_docs_indexed: 0,
        time_finished: isoAfter(START, 2 * MINUTE_MS),
        time_updated: isoAfter(START, 2 * MINUTE_MS),
      })
    );

    expect(
      screen.getByText(
        copy("admin.connector.runs.detail.runtime", { duration: "2 min" })
      )
    ).toBeInTheDocument();
  });

  it("AC-2: a group sync reads memberships/min while running and rate (duration) when done", () => {
    const running = renderLine(
      groupSyncRun({
        status: PermissionSyncStatusEnum.IN_PROGRESS,
        time_started: new Date(Date.now() - 5 * MINUTE_MS).toISOString(),
        time_finished: null,
      })
    );
    // The live rate moves with the clock, so only its shape is pinned.
    const live = new RegExp(
      `^${copy("admin.connector.runs.detail.membershipRate", {
        rate: "RATE",
      })
        .replace(/[.*+?^${}()|[\]\\/]/g, "\\$&")
        .replace("RATE", "\\d+\\.\\d{2}")}$`
    );
    expect(screen.getByText(live)).toBeInTheDocument();
    running.unmount();

    renderLine(groupSyncRun({}));
    expect(
      screen.getByText(
        copy("admin.connector.runs.detail.membershipRateFinished", {
          rate: "25.00",
          duration: "5 min",
        })
      )
    ).toBeInTheDocument();
  });

  it("AC-2: hides new, updated and removed sub-counts that are zero and keeps the nonzero ones", () => {
    // 125 indexed, all new: updated and removed are zero.
    const { container, unmount } = renderLine(
      indexRun({ new_docs_indexed: 125, total_docs_indexed: 125 })
    );
    const counts = lineParts(container).part(screen.getByText("indexed"));
    expect(within(counts).queryByText("0")).toBeNull();
    expect(within(counts).getAllByText("125")).toHaveLength(2);
    unmount();

    // 25 updated, nothing new or removed.
    const updatedOnly = renderLine(
      indexRun({ new_docs_indexed: 0, total_docs_indexed: 25 })
    );
    const updatedCounts = lineParts(updatedOnly.container).part(
      screen.getByText("indexed")
    );
    expect(within(updatedCounts).queryByText("0")).toBeNull();
    expect(within(updatedCounts).getAllByText("25")).toHaveLength(2);
    updatedOnly.unmount();

    // A group sync that touched users but no groups.
    const sync = renderLine(groupSyncRun({ total_groups_processed: 0 }));
    const syncCounts = lineParts(sync.container).part(
      screen.getByText("synced")
    );
    expect(within(syncCounts).queryByText("0")).toBeNull();
    expect(within(syncCounts).getByText("122")).toBeInTheDocument();
  });

  it("AC-1: a clean finished run keeps View Logs hidden until the line is hovered", () => {
    const { container } = renderLine(indexRun());

    const logs = screen.getByRole("button", { name: "View Logs" });
    const chain = selfAndAncestors(logs, container);
    const classes = classesOf(chain);
    expect(classes).toContain("opacity-0");
    const reveal = classes.find((name) =>
      /^group-hover(\/[\w-]+)?:opacity-100$/.test(name)
    );
    expect(reveal).toBeDefined();
    // The hover group is the run line, an ancestor of the button.
    const groupName = reveal!.match(/^group-hover(\/[\w-]+)?:/)![1] ?? "";
    expect(classes).toContain(`group${groupName}`);
  });

  it("AC-1: a run with errors always shows View Logs, also without a run-level error message", () => {
    const { container, unmount } = renderLine(
      indexRun({ error_count: 2, open_error_count: 2, open_doc_error_count: 2 })
    );
    const logs = screen.getByRole("button", { name: "View Logs" });
    expect(classesOf(selfAndAncestors(logs, container))).not.toContain(
      "opacity-0"
    );
    unmount();

    const failed = renderLine(
      indexRun({ status: "failed", error_msg: "Connector timed out" })
    );
    const failedLogs = screen.getByRole("button", { name: "View Logs" });
    expect(
      classesOf(selfAndAncestors(failedLogs, failed.container))
    ).not.toContain("opacity-0");
  });

  it("AC-1: D holds Cancel only while an index run is running and the caller may operate, and View Logs on every run", async () => {
    const user = setupUser();
    const running = renderLine(indexRun(runningAttempt(5)));
    const { part } = lineParts(running.container);
    const d = part(screen.getByRole("button", { name: "View Logs" }));
    const cancel = within(d).getByRole("button", { name: "Cancel" });
    await user.click(cancel);
    expect(running.onCancel).toHaveBeenCalledTimes(1);
    running.unmount();

    const noPermission = renderLine(indexRun(runningAttempt(5)), false);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    noPermission.unmount();

    renderLine(indexRun());
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(
      screen.getByRole("button", { name: "View Logs" })
    ).toBeInTheDocument();
  });

  it("AC-5: a finished retry run reads Document Index - Retry with refresh-cw, its start time and an index run's stages, counts and logs", () => {
    const refresh = referencePaths(SvgRefreshCw);
    const { container } = renderLine(indexRun({}, { is_retry: true }));

    const label = screen.getByText(copy("admin.connector.runs.kinds.retry"));
    expect(iconPaths(nearestIcon(label))).toEqual(refresh);
    const { part } = lineParts(container);
    const a = part(label);
    expect(within(a).getByText(formatDateTimeLog(START))).toBeInTheDocument();
    expect(screen.queryByText("Document Index")).toBeNull();
    expect(
      screen.getByRole("button", { name: "View Stage Metrics" })
    ).toBeInTheDocument();
    expect(screen.getByText("indexed")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "View Logs" })
    ).toBeInTheDocument();
  });

  it("AC-5: a running retry run reads Document Index - Retry and can be canceled", () => {
    renderLine(indexRun(runningAttempt(5), { is_retry: true }));

    expect(
      screen.getByText(copy("admin.connector.runs.kinds.retry"))
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
  });

  it("AC-1 (narrow): below 640 px the start time and the type sit side by side in A", () => {
    const { container } = renderLine(indexRun());

    const type = screen.getByText("Document Index");
    const time = screen.getByText(formatDateTimeLog(START));
    const { part } = lineParts(container);
    expect(part(time)).toBe(part(type));
    const shared = nearestCommonAncestor(type, time);
    expect(
      hasClass(shared, `${BELOW_640}flex-row(?:-reverse)?`) ||
        // Already a row at every width.
        hasClass(shared, "flex-row")
    ).toBe(true);
  });
});
