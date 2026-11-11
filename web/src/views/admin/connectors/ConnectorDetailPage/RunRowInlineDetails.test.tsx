/** A run line's stage details and check results open inline under the line in the runs list, one at a time. */
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import type {
  CCPairRun,
  CCPairRunsResponse,
  CheckRunSnapshot,
} from "@/lib/connectors/types";
import type { CapabilityCheckResult } from "@/lib/connectors/checks/types";
import type {
  IndexAttemptStage,
  IndexAttemptStageMetric,
  IndexAttemptStageMetricsResponse,
} from "@/lib/types";
import RunsCard from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import { formatDateTimeLog } from "@/lib/dateUtils";
import englishMessages from "@/i18n/messages/en.json";

const CC_PAIR_ID = 7;
const MINUTE_MS = 60_000;
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

const STAGES_HINT = copy("admin.connector.runs.actions.stages");
const CHECKS_HINT = copy("admin.connector.runs.actions.checks");
const CLOSE_STAGES = copy("admin.connector.stageDetails.close");
const CLOSE_CHECKS = copy("admin.connector.runs.checkResults.close");

// Pipeline order of the stage lines.
const BUCKET_LABELS = [
  "fetchSource",
  "batchPreProcessing",
  "chunking",
  "embedding",
  "vectorDbWrite",
  "postProcessing",
].map((bucket) => copy(`admin.connector.stageMetrics.buckets.${bucket}.label`));

/** A finished index run. Its `indexed` count differs per line. */
function indexRun(id: number, indexed: number): CCPairRun {
  return {
    kind: "indexing",
    time_created: isoAfter(START, -id * MINUTE_MS),
    resolved_at: null,
    superseded: false,
    is_retry: false,
    attempt: {
      id,
      status: "success",
      from_beginning: false,
      new_docs_indexed: indexed,
      docs_removed_from_index: 0,
      total_docs_indexed: indexed,
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
    },
  } as CCPairRun;
}

function checkResult(
  checkId: string,
  status: CapabilityCheckResult["status"]
): CapabilityCheckResult {
  return {
    capability: "indexing",
    check_id: checkId,
    display_name: `Check ${checkId}`,
    required: false,
    status,
    message: status === "failed" ? `Check ${checkId} failed` : "",
    summary: null,
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

const CHECK_ATTEMPT: CheckRunSnapshot = {
  id: 9,
  status: "failed",
  trigger: "manual",
  check_results: [
    checkResult("a", "failed"),
    checkResult("b", "passed"),
    checkResult("c", "passed"),
  ],
  error_message: null,
  time_created: START,
  time_started: START,
  time_finished: isoAfter(START, MINUTE_MS),
};

const CHECK_RUN: CCPairRun = {
  kind: "checks",
  time_created: isoAfter(START, -9 * MINUTE_MS),
  resolved_at: null,
  superseded: false,
  attempt: CHECK_ATTEMPT,
};

function metric(
  stage: IndexAttemptStage,
  overrides: Partial<IndexAttemptStageMetric> = {}
): IndexAttemptStageMetric {
  return {
    stage,
    scope: "BATCH_LEVEL",
    event_count: 125,
    total_duration_ms: 0,
    avg_duration_ms: 500,
    std_dev_duration_ms: 100,
    min_duration_ms: 200,
    max_duration_ms: 1000,
    time_first_event: null,
    time_last_event: null,
    ...overrides,
  };
}

// The header's figures: 125 batches, 9.860s ± 2.140s on average, 21.400s at most.
const TOTAL = metric("BATCH_TOTAL", {
  event_count: 125,
  avg_duration_ms: 9860,
  std_dev_duration_ms: 2140,
  max_duration_ms: 21400,
});

// One stage per bucket, so every bucket has a line.
const ALL_STAGES: IndexAttemptStageMetric[] = [
  TOTAL,
  metric("CONNECTOR_FETCH"),
  metric("DOC_BATCH_STORE"),
  metric("CHUNKING"),
  metric("EMBEDDING"),
  metric("VECTOR_DB_WRITE"),
  metric("POST_INDEX_DB_UPDATE"),
];

interface Setup {
  runs: CCPairRun[];
  stages?: Record<number, IndexAttemptStageMetric[]>;
}

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

const realFetch = global.fetch;
afterEach(() => {
  global.fetch = realFetch;
});

/** Serves the run list and each attempt's stage metrics. Any other request stays pending. */
function stubApi({ runs, stages = {} }: Setup) {
  const response: CCPairRunsResponse = {
    items: runs,
    total_items: runs.length,
    kinds: ["indexing", "checks"],
    status_counts: {
      running: 0,
      succeeded: runs.length,
      failed: 0,
      canceled: 0,
    },
  } as CCPairRunsResponse;
  global.fetch = jest.fn((input: RequestInfo | URL) => {
    const url = String(input);
    const stageMatch = url.match(/\/index-attempt\/(\d+)\/stage-metrics/);
    if (stageMatch) {
      const body: IndexAttemptStageMetricsResponse = {
        stages: stages[Number(stageMatch[1])] ?? [],
      } as IndexAttemptStageMetricsResponse;
      return Promise.resolve(jsonResponse(body));
    }
    if (url.includes(`/cc-pair/${CC_PAIR_ID}/runs?`)) {
      return Promise.resolve(jsonResponse(response));
    }
    return new Promise<Response>(() => {});
  }) as typeof fetch;
}

async function renderRuns(setup: Setup) {
  stubApi(setup);
  const view = render(<RunsCard ccPairId={CC_PAIR_ID} canOperate />);
  await screen.findAllByText("indexed");
  return view;
}

/** True when `later` comes after `earlier` in document order. */
function follows(earlier: Node, later: Node): boolean {
  return Boolean(
    earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING
  );
}

/** Whether `element` or an ancestor inside `root` carries `opacity-50`. */
function faded(element: Element, root: Element): boolean {
  let current: Element | null = element;
  while (current !== null && current !== root) {
    if (current.classList.contains("opacity-50")) return true;
    current = current.parentElement;
  }
  return false;
}

/** The card sits in the list itself, after `line` and before `next`, not in a floating layer. */
function expectInlineBetween(
  card: Element,
  container: Element,
  line: Element,
  next: Element | null
) {
  expect(container.contains(card)).toBe(true);
  expect(card.closest("[data-radix-popper-content-wrapper]")).toBeNull();
  expect(card.closest('[role="dialog"]')).toBeNull();
  expect(follows(line, card)).toBe(true);
  if (next !== null) expect(follows(card, next)).toBe(true);
}

/** A run line's start time, unique per line, stands for the line. */
function line(run: CCPairRun): HTMLElement {
  return screen.getByText(formatDateTimeLog(run.time_created));
}

function stageHints(): HTMLElement[] {
  return screen.getAllByRole("button", { name: STAGES_HINT });
}

describe("RunRow inline details (FE-7)", () => {
  const FIRST = indexRun(1, 111);
  const SECOND = indexRun(2, 222);
  const RUNS = [FIRST, SECOND, CHECK_RUN];
  const STAGES = { 1: ALL_STAGES, 2: ALL_STAGES };

  it("AC-3: the stage hint opens Stage Details inline under its line with the header figures, and the other lines fade", async () => {
    const user = setupUser();
    const { container } = await renderRuns({ runs: RUNS, stages: STAGES });

    await user.click(stageHints()[0]!);
    const close = await screen.findByRole("button", { name: CLOSE_STAGES });

    const first = line(FIRST);
    const second = line(SECOND);
    expectInlineBetween(close, container, first, second);

    const titleWords = copy("admin.connector.stageDetails.title").replace(
      /\s/g,
      ""
    );
    expect(container.textContent!.replace(/\s/g, "")).toContain(titleWords);
    for (const label of [
      copy("admin.connector.stageDetails.calls"),
      copy("admin.connector.stageDetails.averageTime"),
      copy("admin.connector.stageDetails.maxTime"),
    ]) {
      const heading = screen.getByText(label);
      expect(container.contains(heading)).toBe(true);
      expect(follows(first, heading) && follows(heading, second)).toBe(true);
    }
    expect(await screen.findByText("9.860s")).toBeInTheDocument();
    expect(screen.getByText(/2\.140s/)).toBeInTheDocument();
    expect(screen.getByText("21.400s")).toBeInTheDocument();
    expect(screen.getAllByText("125").length).toBeGreaterThanOrEqual(1);

    expect(faded(first, container)).toBe(false);
    expect(faded(close, container)).toBe(false);
    expect(faded(second, container)).toBe(true);
    expect(faded(line(CHECK_RUN), container)).toBe(true);
  });

  it("AC-3: the stage card lists one stage line per bucket in spec order", async () => {
    const user = setupUser();
    const { container } = await renderRuns({ runs: RUNS, stages: STAGES });

    await user.click(stageHints()[0]!);
    const close = await screen.findByRole("button", { name: CLOSE_STAGES });
    const lines = await Promise.all(
      BUCKET_LABELS.map((label) => screen.findByText(label))
    );

    const second = line(SECOND);
    let previous: Element = close;
    for (const line of lines) {
      expect(container.contains(line)).toBe(true);
      expect(follows(previous, line)).toBe(true);
      previous = line;
    }
    expect(follows(previous, second)).toBe(true);
  });

  it("AC-3: opening another line's stage details closes the first, one card at a time", async () => {
    const user = setupUser();
    const { container } = await renderRuns({ runs: RUNS, stages: STAGES });

    await user.click(stageHints()[0]!);
    await screen.findByRole("button", { name: CLOSE_STAGES });
    await user.click(stageHints()[1]!);

    await waitFor(() => {
      const closes = screen.getAllByRole("button", { name: CLOSE_STAGES });
      expect(closes).toHaveLength(1);
      // Now under the second line, after it and before the checks line.
      expect(follows(line(SECOND), closes[0]!)).toBe(true);
    });
    const close = screen.getByRole("button", { name: CLOSE_STAGES });
    expectInlineBetween(close, container, line(SECOND), line(CHECK_RUN));
    expect(faded(line(FIRST), container)).toBe(true);
    expect(faded(line(SECOND), container)).toBe(false);
  });

  it("AC-3: the × closes the card and the other lines come back", async () => {
    const user = setupUser();
    const { container } = await renderRuns({ runs: RUNS, stages: STAGES });

    await user.click(stageHints()[0]!);
    const close = await screen.findByRole("button", { name: CLOSE_STAGES });
    expectInlineBetween(close, container, line(FIRST), line(SECOND));

    await user.click(close);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: CLOSE_STAGES })).toBeNull()
    );
    expect(faded(line(SECOND), container)).toBe(false);
  });

  it("AC-3: a second click on the same stage hint closes the card", async () => {
    const user = setupUser();
    const { container } = await renderRuns({ runs: RUNS, stages: STAGES });

    await user.click(stageHints()[0]!);
    const close = await screen.findByRole("button", { name: CLOSE_STAGES });
    expectInlineBetween(close, container, line(FIRST), line(SECOND));

    await user.click(stageHints()[0]!);
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: CLOSE_STAGES })).toBeNull()
    );
    expect(faded(line(SECOND), container)).toBe(false);
  });

  it("AC-3: the checks hint opens the check results inline under the checks line and fades the others", async () => {
    const user = setupUser();
    const { container } = await renderRuns({ runs: RUNS, stages: STAGES });

    await user.click(screen.getByRole("button", { name: CHECKS_HINT }));
    const close = await screen.findByRole("button", { name: CLOSE_CHECKS });

    const checksLine = line(CHECK_RUN);
    expectInlineBetween(close, container, checksLine, null);
    // The line's own type reads "Connector Checks" too, so the card's title is the one after the line.
    const titles = screen
      .getAllByText(copy("admin.connector.runs.checkResults.title"))
      .filter((title) => follows(checksLine, title));
    expect(titles).toHaveLength(1);
    expect(container.contains(titles[0]!)).toBe(true);
    expect(
      screen.getByText(
        copy("admin.connector.runs.checkResults.count", { count: "3" })
      )
    ).toBeInTheDocument();
    expect(screen.getByText("Check a failed")).toBeInTheDocument();

    expect(faded(checksLine, container)).toBe(false);
    expect(faded(line(FIRST), container)).toBe(true);
    expect(faded(line(SECOND), container)).toBe(true);
  });

  it("AC-4: a run with no indexed docs shows No docs completed indexing, only the stages that ran, then Later stages canceled", async () => {
    const user = setupUser();
    const noDocs = indexRun(3, 0);
    const { container } = await renderRuns({
      runs: [noDocs, indexRun(2, 222)],
      stages: {
        3: [
          metric("BATCH_TOTAL", { event_count: 0 }),
          metric("CONNECTOR_FETCH"),
          metric("DOC_BATCH_STORE"),
        ],
      },
    });

    await user.click(stageHints()[0]!);
    const close = await screen.findByRole("button", { name: CLOSE_STAGES });
    expectInlineBetween(close, container, line(noDocs), line(SECOND));

    expect(
      await screen.findByText(copy("admin.connector.stageDetails.noDocs"))
    ).toBeInTheDocument();
    expect(screen.getByText(BUCKET_LABELS[0]!)).toBeInTheDocument();
    expect(screen.getByText(BUCKET_LABELS[1]!)).toBeInTheDocument();
    const canceled = screen.getByText(
      copy("admin.connector.stageDetails.laterCanceled")
    );
    expect(follows(screen.getByText(BUCKET_LABELS[1]!), canceled)).toBe(true);
    // Stages that never ran are not listed.
    for (const label of BUCKET_LABELS.slice(2)) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });
});
