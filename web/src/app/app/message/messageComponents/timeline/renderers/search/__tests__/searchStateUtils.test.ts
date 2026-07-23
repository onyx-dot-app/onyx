import {
  constructCurrentSearchState,
  formatSearchHeader,
  formatTimeWindow,
} from "../searchStateUtils";
import {
  SearchToolFilterDelta,
  SearchToolPacket,
} from "@/app/app/services/streamingModels";

function filterPacket(obj: Partial<SearchToolFilterDelta>): SearchToolPacket {
  return {
    placement: { turn_index: 0 },
    obj: { type: "search_tool_filter_delta", sources: [], ...obj },
  };
}

describe("formatTimeWindow", () => {
  it("returns null when there is no time filter", () => {
    expect(formatTimeWindow(null)).toBeNull();
    expect(formatTimeWindow({ start: null, end: null })).toBeNull();
  });

  it("phrases a lower-bound-only window as 'since'", () => {
    expect(formatTimeWindow({ start: "2024-01-05T12:00:00Z", end: null })).toBe(
      "since Jan 5, 2024"
    );
  });

  it("phrases an upper-bound-only window as 'before'", () => {
    expect(formatTimeWindow({ start: null, end: "2024-03-10T12:00:00Z" })).toBe(
      "before Mar 10, 2024"
    );
  });

  it("formats day boundaries as their UTC date regardless of local timezone", () => {
    // A single-day window as the backend emits it: midnight to end-of-day UTC.
    expect(
      formatTimeWindow({
        start: "2026-07-15T00:00:00+00:00",
        end: "2026-07-15T23:59:59.999999+00:00",
      })
    ).toBe("from Jul 15, 2026 to Jul 15, 2026");
  });

  it("phrases a bounded window as 'from ... to ...'", () => {
    expect(
      formatTimeWindow({
        start: "2024-01-05T12:00:00Z",
        end: "2024-03-10T12:00:00Z",
      })
    ).toBe("from Jan 5, 2024 to Mar 10, 2024");
  });
});

describe("formatSearchHeader", () => {
  it("appends the time window to the default header", () => {
    expect(
      formatSearchHeader([], { start: "2024-01-05T12:00:00Z", end: null })
    ).toBe("Searching internal documents (since Jan 5, 2024)");
  });

  it("leaves the header untouched when no time window applies", () => {
    expect(formatSearchHeader([])).toBe("Searching internal documents");
    expect(formatSearchHeader([], null)).toBe("Searching internal documents");
  });
});

describe("constructCurrentSearchState filter extraction", () => {
  it("unions sources and takes the latest time window from filter deltas", () => {
    const state = constructCurrentSearchState([
      filterPacket({ sources: ["slack"] }),
      filterPacket({
        sources: [],
        time_filter_start: "2024-01-05T12:00:00Z",
        time_filter_end: null,
      }),
    ]);
    expect(state.sourceFilters).toEqual(["slack"]);
    expect(state.timeFilter).toEqual({
      start: "2024-01-05T12:00:00Z",
      end: null,
    });
  });

  it("leaves timeFilter null when no delta carries a time bound", () => {
    const state = constructCurrentSearchState([
      filterPacket({ sources: ["slack", "notion"] }),
    ]);
    expect(state.sourceFilters).toEqual(["slack", "notion"]);
    expect(state.timeFilter).toBeNull();
  });
});
