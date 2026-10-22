/** The throughput chart labels its local-time ticks in the browser's zone, and a one-slice selection keeps a neighbor on each side so its bar draws. */
import type { ReactElement } from "react";
import { createFormatter } from "next-intl";
import { render } from "@tests/setup/test-utils";
import type { CCPairThroughputResponse } from "@/lib/connectors/types/ccPair";
import {
  ThroughputBars,
  chartSlices,
  formatSliceRange,
  formatTickLabel,
} from "@/views/admin/connectors/ConnectorDetailPage/ThroughputChart";

// jsdom has no layout, so the responsive container gets a fixed size.
jest.mock("recharts", () => {
  const actual = jest.requireActual<typeof import("recharts")>("recharts");
  const { cloneElement } = jest.requireActual<typeof import("react")>("react");
  return {
    ...actual,
    ResponsiveContainer: ({
      children,
    }: {
      children: ReactElement<{ width?: number; height?: number }>;
    }) => cloneElement(children, { width: 600, height: 120 }),
  };
});

const LOCAL_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
// next-intl formats in the server's zone. Any zone far from the local one shows a missing override.
const SERVER_ZONE =
  LOCAL_ZONE === "Pacific/Kiritimati" ? "Etc/GMT+12" : "Pacific/Kiritimati";
const serverFormat = createFormatter({ locale: "en", timeZone: SERVER_ZONE });

describe("chart labels", () => {
  // Noon UTC is the next day in Kiritimati, so a day label shows the zone too.
  const instant = Date.UTC(2026, 9, 21, 12, 0);

  it("labels a time tick in the browser's zone", () => {
    expect(formatTickLabel(serverFormat, instant, 10)).toBe(
      new Intl.DateTimeFormat("en", {
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(instant)
    );
  });

  it("labels a day tick with the browser's date", () => {
    expect(formatTickLabel(serverFormat, instant, 1440)).toBe(
      new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(
        instant
      )
    );
  });

  it("shows a slice's span in the browser's zone", () => {
    const from = new Date(instant);
    const to = new Date(instant + 20 * 60_000);
    expect(formatSliceRange(serverFormat, from, to)).toBe(
      new Intl.DateTimeFormat("en", {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).formatRange(from, to)
    );
  });
});

describe("chartSlices", () => {
  const SLICE_MS = 60_000;
  const docs = [5, 6, 7, 8, 9];
  const sliceStart = (index: number) => index * SLICE_MS;

  it("keeps every slice when nothing is picked", () => {
    expect(
      chartSlices(docs, 0, SLICE_MS, 0, docs.length * SLICE_MS).map(
        (slice) => slice.docs
      )
    ).toEqual(docs);
  });

  it("keeps one neighbor on each side of a picked slice", () => {
    expect(
      chartSlices(docs, 0, SLICE_MS, sliceStart(2), sliceStart(3)).map(
        (slice) => slice.docs
      )
    ).toEqual([6, 7, 8]);
  });

  it("keeps the one neighbor a slice at the window's edge has", () => {
    expect(
      chartSlices(docs, 0, SLICE_MS, sliceStart(0), sliceStart(1)).map(
        (slice) => slice.docs
      )
    ).toEqual([5, 6]);
  });

  it("puts each bar at its slice's middle", () => {
    expect(chartSlices([1], 1_000, SLICE_MS, 1_000, 61_000)).toEqual([
      { at: 31_000, docs: 1 },
    ]);
  });
});

describe("a picked slice", () => {
  it("draws its bar", () => {
    const start = Date.UTC(2026, 9, 21, 0, 0);
    const sliceMs = 3 * 60_000;
    const data: CCPairThroughputResponse = {
      window_start: new Date(start).toISOString(),
      window_end: new Date(start + 20 * sliceMs).toISOString(),
      docs_indexed: Array.from({ length: 20 }, () => 5),
      runs: [],
    };

    const { container } = render(
      <ThroughputBars
        data={data}
        range="1h"
        selection={{
          since: new Date(start + 7 * sliceMs).toISOString(),
          until: new Date(start + 8 * sliceMs).toISOString(),
        }}
      />
    );

    // Recharts skips a zero-width rectangle, so a lone bar with no neighbors draws nothing.
    expect(
      container.querySelectorAll(".recharts-rectangle").length
    ).toBeGreaterThan(0);
  });
});
