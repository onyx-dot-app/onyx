import { createTranslator } from "next-intl";
import en from "@/i18n/messages/en.json";
import ar from "@/i18n/messages/ar.json";
import type { TimelineTranslate } from "@/app/app/message/messageComponents/toolDisplayHelpers";
import {
  constructCurrentSearchState,
  formatSearchHeader,
  formatTimeWindow,
} from "@/app/app/message/messageComponents/timeline/renderers/search/searchStateUtils";
import { ResponseItem, SearchResult } from "@/app/app/services/streamingModels";
import { responseItem } from "@/app/app/message/messageComponents/timeline/hooks/__tests__/testHelpers";

function searchItem(metadata: Partial<SearchResult>): ResponseItem {
  return responseItem({
    kind: "tool",
    name: "internal_search",
    arguments: {},
    status: "running",
    output: "",
    metadata: {
      type: "search_result",
      queries: [],
      sources: [],
      search_docs: [],
      displayed_docs: null,
      time_filter_start: null,
      time_filter_end: null,
      citation_mapping: {},
      ...metadata,
    },
  });
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
  it("reads source and time filters from search result metadata", () => {
    const state = constructCurrentSearchState([
      searchItem({
        sources: ["slack"],
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

  it("leaves timeFilter null when metadata has no time bound", () => {
    const state = constructCurrentSearchState([
      searchItem({ sources: ["slack", "notion"] }),
    ]);
    expect(state.sourceFilters).toEqual(["slack", "notion"]);
    expect(state.timeFilter).toBeNull();
  });
});
