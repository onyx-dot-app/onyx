/** A run line's live sync detail, its logs action with and without logs, the retry glyph while running, and keyboard focus around its inline stage card. */
import { useState } from "react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { SvgRefreshCw } from "@opal/icons";
import {
  PermissionSyncStatusEnum,
  type CCPairRun,
} from "@/lib/connectors/types";
import RunRow from "@/views/admin/connectors/ConnectorDetailPage/RunRow";

const MINUTE_MS = 60_000;
const START = "2026-03-23T10:00:00.000Z";
const FINISH = "2026-03-23T10:05:00.000Z";

type IndexRun = Extract<CCPairRun, { kind: "indexing" }>;

function indexRun(
  attempt: Partial<IndexRun["attempt"]> = {},
  isRetry = false
): CCPairRun {
  return {
    kind: "indexing",
    time_created: START,
    resolved_at: null,
    superseded: false,
    is_retry: isRetry,
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
      time_updated: FINISH,
      time_finished: FINISH,
      is_new_model: false,
      is_backfill: false,
      ...attempt,
    },
  } as CCPairRun;
}

function renderLine(run: CCPairRun) {
  const onViewLogs = jest.fn();
  const view = render(
    <RunRow
      run={run}
      canCancel
      onCancel={jest.fn()}
      onViewLogs={onViewLogs}
      open={false}
      onOpenChange={jest.fn()}
      dimmed={false}
    />
  );
  return { ...view, onViewLogs };
}

/** Owns the open state as the runs card does. */
function OpenableLine({ run }: { run: CCPairRun }) {
  const [open, setOpen] = useState(false);
  return (
    <RunRow
      run={run}
      canCancel
      onCancel={jest.fn()}
      onViewLogs={jest.fn()}
      open={open}
      onOpenChange={setOpen}
      dimmed={false}
    />
  );
}

function iconPaths(svg: Element | null): string[] {
  return Array.from(svg?.querySelectorAll("path") ?? []).map(
    (path) => path.getAttribute("d") ?? ""
  );
}

const realFetch = global.fetch;
afterEach(() => {
  global.fetch = realFetch;
});

describe("RunRow detail", () => {
  it("reads Starting sync for a running permission sync that has synced nothing yet", () => {
    const now = Date.now();
    renderLine({
      kind: "doc_permission_sync",
      time_created: START,
      resolved_at: null,
      superseded: false,
      attempt: {
        id: 51,
        status: PermissionSyncStatusEnum.IN_PROGRESS,
        error_message: null,
        full_exception_trace: null,
        total_docs_synced: 0,
        docs_with_permission_errors: 0,
        time_created: new Date(now - MINUTE_MS).toISOString(),
        time_started: new Date(now - MINUTE_MS).toISOString(),
        time_finished: null,
      },
    });

    expect(screen.getByText("Starting sync")).toBeInTheDocument();
    expect(screen.queryByText(/docs\/min/)).toBeNull();
  });
});

describe("RunRow logs action", () => {
  it("is disabled on a run that recorded no trace or message", async () => {
    const user = setupUser();
    const { onViewLogs } = renderLine(indexRun());

    const logs = screen.getByRole("button", { name: "View Logs" });
    expect(logs).toHaveAttribute("aria-disabled", "true");
    await user.click(logs);
    expect(onViewLogs).not.toHaveBeenCalled();
  });

  it("shows on a clean run while keyboard focus is inside it", () => {
    renderLine(indexRun());

    const logs = screen.getByRole("button", { name: "View Logs" });
    expect(logs.closest(".focus-within\\:opacity-100")).not.toBeNull();
  });

  it("opens the logs of a run that recorded an error", async () => {
    const user = setupUser();
    const { onViewLogs } = renderLine(
      indexRun({ status: "failed", error_msg: "Connector timed out" })
    );

    const logs = screen.getByRole("button", { name: "View Logs" });
    expect(logs).not.toHaveAttribute("aria-disabled");
    await user.click(logs);
    expect(onViewLogs).toHaveBeenCalledTimes(1);
  });
});

describe("RunRow retry glyph", () => {
  it("keeps refresh-cw while a retry runs", () => {
    const now = Date.now();
    const { container, unmount } = render(<SvgRefreshCw size={12} />);
    const refresh = iconPaths(container.querySelector("svg"));
    unmount();

    renderLine(
      indexRun(
        {
          status: "in_progress",
          time_started: new Date(now - 5 * MINUTE_MS).toISOString(),
          time_finished: null,
        },
        true
      )
    );

    const label = screen.getByText("Document Index - Retry");
    expect(iconPaths(label.parentElement!.querySelector("svg"))).toEqual(
      refresh
    );
  });
});

describe("RunRow inline stage card keyboard", () => {
  beforeEach(() => {
    // The card's metrics stay loading; only its header and close matter here.
    global.fetch = jest.fn(
      () => new Promise<Response>(() => {})
    ) as typeof fetch;
  });

  it("tells assistive tech whether the stage hint's card is open", async () => {
    const user = setupUser();
    render(<OpenableLine run={indexRun()} />);
    const hint = screen.getByRole("button", { name: "View Stage Metrics" });
    expect(hint).toHaveAttribute("aria-expanded", "false");

    await user.click(hint);

    expect(hint).toHaveAttribute("aria-expanded", "true");
  });

  it("focuses the close button as the card opens", async () => {
    const user = setupUser();
    render(<OpenableLine run={indexRun()} />);

    await user.click(
      screen.getByRole("button", { name: "View Stage Metrics" })
    );

    expect(
      screen.getByRole("button", { name: "Close stage details" })
    ).toHaveFocus();
  });

  it("closes on Escape and returns focus to the stage hint", async () => {
    const user = setupUser();
    render(<OpenableLine run={indexRun()} />);
    const hint = screen.getByRole("button", { name: "View Stage Metrics" });

    await user.click(hint);
    await user.keyboard("{Escape}");

    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Stage Details" })).toBeNull()
    );
    expect(hint).toHaveFocus();
  });

  it("returns focus to the stage hint after the close button", async () => {
    const user = setupUser();
    render(<OpenableLine run={indexRun()} />);
    const hint = screen.getByRole("button", { name: "View Stage Metrics" });

    await user.click(hint);
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Close stage details" })
      ).toBeNull()
    );
    expect(hint).toHaveFocus();
  });
});
