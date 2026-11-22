import { PostgresToolQuery } from "@/app/app/services/streamingModels";
import {
  formatQueryDate,
  postgresQueryChips,
  postgresQueryFolderId,
  PostgresQueryLabel,
} from "./postgresQueryChips";

const label: PostgresQueryLabel = (key, values) =>
  values ? `${key}(${Object.values(values).join(", ")})` : key;
const sourceName = (source: string) => source.toUpperCase();
const labels = (query: PostgresToolQuery) =>
  postgresQueryChips(query, label, "en-US", sourceName).map(
    (chip) => chip.label
  );

describe("postgresQueryChips", () => {
  test("a folder shows its name once known, else its id", () => {
    const query: PostgresToolQuery = {
      table: "document",
      parent_hierarchy_node_id: 42,
    };
    expect(postgresQueryFolderId(query)).toBe(42);
    expect(labels(query)).toEqual(["table.document", "folder(42)"]);
    expect(
      postgresQueryChips(query, label, "en-US", sourceName, "Engineering").map(
        (chip) => chip.label
      )
    ).toEqual(["table.document", "folder(Engineering)"]);
    expect(
      postgresQueryFolderId({ table: "hierarchy_node", parent_id: 7 })
    ).toBe(7);
    expect(postgresQueryFolderId({ table: "document" })).toBeNull();
  });

  test("a filtered document listing", () => {
    expect(
      labels({
        table: "document",
        source_type: "jira",
        updated_after: "2026-02-01",
        updated_before: "2026-03-01",
        limit: 100,
      })
    ).toEqual([
      "table.document",
      "JIRA",
      "updated.between(Feb 1, 2026, Mar 1, 2026)",
    ]);
  });

  test("a later page and a grouped count", () => {
    expect(
      labels({ table: "document", title_contains: "B200", cursor: "abc" })
    ).toEqual(["table.document", "titleContains(B200)", "nextPage"]);
    expect(
      labels({ table: "document", count: true, group_by: "owner" })
    ).toEqual(["table.document", "countBy.owner"]);
    expect(labels({ table: "chat_session", count: true })).toEqual([
      "table.chat_session",
      "count",
    ]);
  });

  test("one-sided date ranges and chat filters", () => {
    expect(
      labels({
        table: "chat_message",
        sent_after: "2025-12-31",
        content_contains: "quota",
        message_type: "user",
      })
    ).toEqual([
      "table.chat_message",
      "textContains(quota)",
      "sent.since(Dec 31, 2025)",
      "author(user)",
    ]);
  });

  test("unknown values and empty arguments add no chips", () => {
    expect(
      labels({ table: "nope", group_by: "x", title_contains: " " })
    ).toEqual([]);
    expect(labels({})).toEqual([]);
  });
});

describe("formatQueryDate", () => {
  test("formats the UTC day, and keeps text it cannot parse", () => {
    expect(formatQueryDate("2026-03-01", "en-US")).toBe("Mar 1, 2026");
    expect(formatQueryDate("last tuesday", "en-US")).toBe("last tuesday");
  });
});
