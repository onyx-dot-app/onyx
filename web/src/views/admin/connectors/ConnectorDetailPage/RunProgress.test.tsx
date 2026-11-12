/** The progress of a conversion run: the count so far while the listing runs, then one bar for each stage, the skipped count and the ETA. */
import { render, screen } from "@tests/setup/test-utils";
import type { IndexAttemptProgress } from "@/lib/types";
import type { CCPairRun } from "@/lib/connectors/types";
import RunProgress from "@/views/admin/connectors/ConnectorDetailPage/RunProgress";
import RunRow from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

const START = "2026-03-23T10:00:00.000Z";

function progress(
  overrides: Partial<IndexAttemptProgress> = {}
): IndexAttemptProgress {
  return {
    listing_done: true,
    docs_listed: 1000,
    docs_skipped: 0,
    docs_indexed: 250,
    docs_failed: 0,
    batches_listed: 20,
    batches_converted: 10,
    batches_indexed: 5,
    batches_total: 20,
    eta_seconds: null,
    ...overrides,
  };
}

function indexRun(
  status: "in_progress" | "success",
  runProgress: IndexAttemptProgress | null
): CCPairRun {
  return {
    kind: "indexing",
    time_created: START,
    resolved_at: null,
    superseded: false,
    is_retry: false,
    attempt: {
      id: 31,
      status,
      from_beginning: false,
      new_docs_indexed: 100,
      docs_removed_from_index: 0,
      total_docs_indexed: 250,
      error_msg: null,
      error_count: 0,
      open_error_count: 0,
      open_doc_error_count: 0,
      full_exception_trace: null,
      time_started: START,
      time_updated: START,
      time_finished: status === "success" ? START : null,
      is_new_model: false,
      is_backfill: false,
      progress: runProgress,
    },
  } as CCPairRun;
}

function renderRow(run: CCPairRun) {
  return render(
    <RunRow
      run={run}
      canCancel
      onCancel={jest.fn()}
      onViewLogs={jest.fn()}
      open={false}
      onOpenChange={jest.fn()}
      dimmed={false}
    />
  );
}

describe("RunProgress", () => {
  it("shows the count so far while the listing runs", () => {
    render(
      <RunProgress
        progress={progress({
          listing_done: false,
          batches_total: null,
          docs_listed: 1234,
        })}
      />
    );

    expect(screen.getByText("Listed 1,234 documents so far")).toBeVisible();
    expect(screen.queryAllByRole("progressbar")).toHaveLength(0);
  });

  it("shows a bar with a percentage for each stage when the listing is done", () => {
    render(<RunProgress progress={progress()} />);

    expect(screen.getByRole("progressbar", { name: "Listed" })).toHaveAttribute(
      "aria-valuenow",
      "20"
    );
    expect(
      screen.getByRole("progressbar", { name: "Converted" })
    ).toHaveAttribute("aria-valuenow", "10");
    expect(
      screen.getByRole("progressbar", { name: "Indexed" })
    ).toHaveAttribute("aria-valuenow", "5");
    expect(screen.getByText("100%")).toBeVisible();
    expect(screen.getByText("50%")).toBeVisible();
    expect(screen.getByText("25%")).toBeVisible();
  });

  it("shows the ETA and the skipped documents when there are any", () => {
    render(
      <RunProgress progress={progress({ eta_seconds: 252, docs_skipped: 3 })} />
    );

    expect(screen.getByText("About 4 min 12 sec left")).toBeVisible();
    expect(screen.getByText("3 unchanged documents skipped")).toBeVisible();
  });

  it("shows no ETA and no skipped count when there are none", () => {
    render(<RunProgress progress={progress()} />);

    expect(screen.queryByText(/left$/)).not.toBeInTheDocument();
    expect(screen.queryByText(/skipped$/)).not.toBeInTheDocument();
  });
});

describe("RunRow progress", () => {
  it("shows the progress of a running conversion run", () => {
    renderRow(indexRun("in_progress", progress()));

    expect(screen.getByTestId("run-progress")).toBeVisible();
    expect(screen.getByTestId("run-row")).toContainElement(
      screen.getByTestId("run-progress")
    );
  });

  it("shows no progress for a run without the conversion stage", () => {
    renderRow(indexRun("in_progress", null));

    expect(screen.queryByTestId("run-progress")).not.toBeInTheDocument();
  });

  it("shows no progress after the run ended", () => {
    renderRow(indexRun("success", progress()));

    expect(screen.queryByTestId("run-progress")).not.toBeInTheDocument();
  });
});
