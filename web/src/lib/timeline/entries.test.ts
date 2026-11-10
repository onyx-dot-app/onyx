import {
  groupTimelineEntries,
  setTimelineEntryStatus,
  upsertTimelineEntry,
} from "@/lib/timeline/entries";
import type { TimelineEntry } from "@/lib/timeline/types";

function entry(
  id: string,
  groupId: string | null = null,
  payload = id
): TimelineEntry<string> {
  return { id, status: "streaming", groupId, payload };
}

describe("upsertTimelineEntry", () => {
  it("updates an earlier entry in place and appends new ids", () => {
    const entries = [entry("a"), entry("b")];

    const updated = upsertTimelineEntry(entries, entry("a", null, "a2"));
    const appended = upsertTimelineEntry(updated, entry("c"));

    expect(appended.map((e) => e.payload)).toEqual(["a2", "b", "c"]);
  });
});

describe("setTimelineEntryStatus", () => {
  it("sets only the matching entry", () => {
    const entries = setTimelineEntryStatus(
      [entry("a"), entry("b")],
      "b",
      "done"
    );

    expect(entries.map((e) => e.status)).toEqual(["streaming", "done"]);
  });
});

describe("groupTimelineEntries", () => {
  it("keeps first-seen group order and gives ungrouped entries their own group", () => {
    const groups = groupTimelineEntries([
      entry("0-0", "0"),
      entry("0-1", "0"),
      entry("solo"),
      entry("1-0", "1"),
    ]);

    expect(
      groups.map((group) => [group.id, group.entries.map((e) => e.id)])
    ).toEqual([
      ["0", ["0-0", "0-1"]],
      ["solo", ["solo"]],
      ["1", ["1-0"]],
    ]);
    expect(groups.map((group) => group.isParallel)).toEqual([
      true,
      false,
      false,
    ]);
  });
});
