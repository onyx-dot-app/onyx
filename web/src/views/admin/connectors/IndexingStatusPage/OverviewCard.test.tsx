/** The status page's overview: the fetch carries the chart's bar count and the browser's clock, the old window's bars pick nothing while a new one loads, and a failed refresh never leaves old counts looking current. */
import { fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { render, screen, setupUser } from "@tests/setup/test-utils";
import type { IndexingOverviewResponse } from "@/lib/connectors/types";
import OverviewCard from "@/views/admin/connectors/IndexingStatusPage/OverviewCard";
import {
  FIXTURE_BINS,
  installChartLayout,
  isFaded,
  resetChartLayout,
  throughputFixture,
} from "@tests/setup/throughputChartTestUtils";

const originalFetch = global.fetch;

afterEach(() => {
  resetChartLayout();
  global.fetch = originalFetch;
  jest.restoreAllMocks();
});

function overviewCalls(fetchMock: jest.Mock): URLSearchParams[] {
  return fetchMock.mock.calls
    .map(([input]) => String(input))
    .filter((url) =>
      url.includes("/api/manage/admin/index-monitoring/overview")
    )
    .map((url) => new URL(url, "http://localhost").searchParams);
}

it("asks for the overview with the chart's bar count and the browser's clock", async () => {
  jest.spyOn(Date.prototype, "getTimezoneOffset").mockReturnValue(-120);
  installChartLayout(472);
  const overview: IndexingOverviewResponse = {
    indexing_connectors: 1,
    active_connectors: 2,
    recent_docs_indexed: 3,
    total_docs_indexed: 4,
    throughput: throughputFixture(),
  };
  const fetchMock = jest.fn(
    async () =>
      new Response(JSON.stringify(overview), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
  );
  global.fetch = fetchMock as unknown as typeof fetch;

  const { container } = render(
    <OverviewCard
      range={null}
      onRangeChange={() => {}}
      panelOpen={false}
      onPanelOpenChange={() => {}}
    />
  );

  await waitFor(() =>
    expect(
      container.querySelectorAll('[data-testid="chart-bar"]')
    ).toHaveLength(FIXTURE_BINS)
  );
  const calls = overviewCalls(fetchMock);
  expect(calls).not.toEqual([]);
  for (const params of calls) {
    expect(params.get("window")).toBe("1h");
    expect(params.get("bins")).toBe("48");
    expect(params.get("tz_offset_minutes")).toBe("120");
  }
});

it("ignores clicks on the old window's bars while a new window loads", async () => {
  installChartLayout(600);
  const overview: IndexingOverviewResponse = {
    indexing_connectors: 1,
    active_connectors: 2,
    recent_docs_indexed: 3,
    total_docs_indexed: 4,
    throughput: throughputFixture({ docs: { 2: 40 } }),
  };
  global.fetch = jest.fn((input: RequestInfo | URL) =>
    String(input).includes("window=1h")
      ? Promise.resolve(
          new Response(JSON.stringify(overview), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
        )
      : new Promise<Response>(() => {})
  ) as unknown as typeof fetch;
  const onRangeChange = jest.fn();
  const user = setupUser();
  const { container } = render(
    <OverviewCard
      range={null}
      onRangeChange={onRangeChange}
      panelOpen={false}
      onPanelOpenChange={() => {}}
    />
  );
  const bars = () =>
    Array.from(container.querySelectorAll('[data-testid="chart-bar"]'));
  await waitFor(() => expect(bars()).toHaveLength(FIXTURE_BINS));

  await user.click(screen.getByRole("button", { name: /Last hour/ }));
  await user.click(await screen.findByText("Last 7 days"));
  await waitFor(() => expect(isFaded(bars()[2]!, container)).toBe(true));
  onRangeChange.mockClear();

  fireEvent.click(bars()[2]!);
  fireEvent.keyDown(bars()[2]!, { key: "Enter" });

  expect(onRangeChange).not.toHaveBeenCalled();
});

it("shows dashes, not the last window's counts, once a refresh fails", async () => {
  installChartLayout(472);
  const overview: IndexingOverviewResponse = {
    indexing_connectors: 1,
    active_connectors: 21,
    recent_docs_indexed: 3,
    total_docs_indexed: 43,
    paused_connectors: 65,
    throughput: throughputFixture(),
  };
  // Only the first window loads, so picking another fails while SWR keeps the first response.
  global.fetch = jest.fn(async (input: RequestInfo | URL) =>
    String(input).includes("window=1h")
      ? new Response(JSON.stringify(overview), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
      : new Response("{}", { status: 500 })
  ) as unknown as typeof fetch;
  const user = userEvent.setup();

  render(
    <OverviewCard
      range={null}
      onRangeChange={() => {}}
      panelOpen={false}
      onPanelOpenChange={() => {}}
    />
  );
  expect(await screen.findByText("21")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Last hour" }));
  await user.click(
    await screen.findByRole("option", { name: "Last 24 hours" })
  );

  expect(
    await screen.findByText("The overview could not load.")
  ).toBeInTheDocument();
  expect(screen.queryByText("21")).toBeNull();
  expect(screen.queryByText("43")).toBeNull();
  expect(screen.queryByText("65")).toBeNull();
  expect(screen.getAllByText("—")).toHaveLength(3);
});
