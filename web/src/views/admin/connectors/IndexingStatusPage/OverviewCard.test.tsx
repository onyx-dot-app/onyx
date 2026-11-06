/** The status page's chart: the overview fetch carries the chart's bar count and the browser's clock. */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { render, setupUser } from "@tests/setup/test-utils";
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
    <OverviewCard range={null} onRangeChange={() => {}} />
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
    <OverviewCard range={null} onRangeChange={onRangeChange} />
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
