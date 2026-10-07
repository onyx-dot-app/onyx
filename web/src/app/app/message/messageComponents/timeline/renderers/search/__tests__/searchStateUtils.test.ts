import { createTranslator } from "next-intl";
import en from "@/i18n/messages/en.json";
import ar from "@/i18n/messages/ar.json";
import type { TimelineTranslate } from "@/app/app/message/messageComponents/toolDisplayHelpers";
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

// The header helpers take the same translator the renderer gets from
// useTranslations, so the tests build one from the real catalogs.
const tEn = createTranslator({
  locale: "en",
  messages: en,
  namespace: "chat.messages.timeline",
}) as TimelineTranslate;
const tAr = createTranslator({
  locale: "ar",
  messages: ar,
  namespace: "chat.messages.timeline",
}) as TimelineTranslate;

describe("formatTimeWindow", () => {
  it("returns null when there is no time filter", () => {
    expect(formatTimeWindow(null, tEn, "en")).toBeNull();
    expect(formatTimeWindow({ start: null, end: null }, tEn, "en")).toBeNull();
  });

  it("phrases a lower-bound-only window as 'since'", () => {
    expect(
      formatTimeWindow({ start: "2024-01-05T12:00:00Z", end: null }, tEn, "en")
    ).toBe("since Jan 5, 2024");
  });

  it("phrases an upper-bound-only window as 'before'", () => {
    expect(
      formatTimeWindow({ start: null, end: "2024-03-10T12:00:00Z" }, tEn, "en")
    ).toBe("before Mar 10, 2024");
  });

  it("formats day boundaries as their UTC date regardless of local timezone", () => {
    // A single-day window as the backend emits it: midnight to end-of-day UTC.
    expect(
      formatTimeWindow(
        {
          start: "2026-07-15T00:00:00+00:00",
          end: "2026-07-15T23:59:59.999999+00:00",
        },
        tEn,
        "en"
      )
    ).toBe("from Jul 15, 2026 to Jul 15, 2026");
  });

  it("phrases a bounded window as 'from ... to ...'", () => {
    expect(
      formatTimeWindow(
        {
          start: "2024-01-05T12:00:00Z",
          end: "2024-03-10T12:00:00Z",
        },
        tEn,
        "en"
      )
    ).toBe("from Jan 5, 2024 to Mar 10, 2024");
  });

  it("translates the phrase and formats the date in the active locale", () => {
    const window = formatTimeWindow(
      { start: "2024-01-05T12:00:00Z", end: null },
      tAr,
      "ar"
    );
    expect(window).toContain("منذ");
    expect(window).toContain("يناير");
    expect(window).not.toContain("Jan");
  });
});

describe("formatSearchHeader", () => {
  it("appends the time window to the default header", () => {
    expect(
      formatSearchHeader(
        [],
        { start: "2024-01-05T12:00:00Z", end: null },
        tEn,
        "en"
      )
    ).toBe("Searching internal documents (since Jan 5, 2024)");
  });

  it("leaves the header untouched when no time window applies", () => {
    expect(formatSearchHeader([], null, tEn, "en")).toBe(
      "Searching internal documents"
    );
  });

  it("names up to three sources and counts the rest", () => {
    expect(formatSearchHeader(["slack", "notion"], null, tEn, "en")).toBe(
      "Searching Slack, Notion"
    );
    expect(
      formatSearchHeader(
        ["slack", "notion", "confluence", "jira", "github"],
        null,
        tEn,
        "en"
      )
    ).toBe("Searching Slack, Notion, Confluence +2 more");
  });

  it("translates the default header", () => {
    expect(formatSearchHeader([], null, tAr, "ar")).toBe(
      "جارٍ البحث في المستندات الداخلية"
    );
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
