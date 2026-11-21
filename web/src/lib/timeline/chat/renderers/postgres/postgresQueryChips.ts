/**
 * Turns a postgres_query call's arguments into short labels for the step's
 * query summary, e.g. "Documents", "Jira", "Updated Feb 1, 2026 – Mar 1, 2026".
 */

import {
  PostgresToolQuery,
  PostgresToolQueryValue,
} from "@/app/app/services/streamingModels";

/** Keys under `chat.messages.timeline.postgres.query`. */
export type PostgresQueryLabelKey =
  | "table.document"
  | "table.hierarchy_node"
  | "table.chat_session"
  | "table.chat_message"
  | "table.search_doc"
  | "count"
  | "countBy.source"
  | "countBy.owner"
  | "countBy.month"
  | "titleContains"
  | "nameContains"
  | "textContains"
  | "updated.since"
  | "updated.before"
  | "updated.between"
  | "created.since"
  | "created.before"
  | "created.between"
  | "sent.since"
  | "sent.before"
  | "sent.between"
  | "owner"
  | "folder"
  | "nodeType"
  | "author"
  | "message"
  | "allRetrieved"
  | "nextPage";

export interface PostgresQueryChip {
  key: string;
  label: string;
}

export type PostgresQueryLabel = (
  key: PostgresQueryLabelKey,
  values?: Record<string, string>
) => string;

const TABLE_LABELS: Record<string, PostgresQueryLabelKey> = {
  document: "table.document",
  hierarchy_node: "table.hierarchy_node",
  chat_session: "table.chat_session",
  chat_message: "table.chat_message",
  search_doc: "table.search_doc",
};

const GROUP_LABELS: Record<string, PostgresQueryLabelKey> = {
  source: "countBy.source",
  owner: "countBy.owner",
  month: "countBy.month",
};

interface DateRange {
  key: string;
  after: PostgresToolQueryValue | undefined;
  before: PostgresToolQueryValue | undefined;
  since: PostgresQueryLabelKey;
  until: PostgresQueryLabelKey;
  between: PostgresQueryLabelKey;
}

function text(value: PostgresToolQueryValue | undefined): string | null {
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

/** Dates are UTC days, as the tool compares them. */
export function formatQueryDate(value: string, locale: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeZone: "UTC",
  }).format(date);
}

/** The hierarchy node the query lists inside, if any. */
export function postgresQueryFolderId(query: PostgresToolQuery): number | null {
  const folder = text(query.parent_hierarchy_node_id) ?? text(query.parent_id);
  return folder !== null && /^\d+$/.test(folder) ? Number(folder) : null;
}

/** `folderName` is the node's display name, once known; until then the chip shows its id. */
export function postgresQueryChips(
  query: PostgresToolQuery,
  label: PostgresQueryLabel,
  locale: string,
  sourceName: (source: string) => string,
  folderName?: string
): PostgresQueryChip[] {
  const chips: PostgresQueryChip[] = [];
  const add = (
    key: string,
    labelKey: PostgresQueryLabelKey,
    values?: Record<string, string>
  ) => chips.push({ key, label: label(labelKey, values) });

  const table = TABLE_LABELS[text(query.table) ?? ""];
  if (table) add("table", table);

  const source = text(query.source_type);
  if (source) chips.push({ key: "source", label: sourceName(source) });

  const textFilters: [
    string,
    PostgresToolQueryValue | undefined,
    PostgresQueryLabelKey,
  ][] = [
    ["title_contains", query.title_contains, "titleContains"],
    ["description_contains", query.description_contains, "titleContains"],
    ["name_contains", query.name_contains, "nameContains"],
    ["content_contains", query.content_contains, "textContains"],
  ];
  for (const [key, value, labelKey] of textFilters) {
    const filterText = text(value);
    if (filterText) add(key, labelKey, { text: filterText });
  }

  const ranges: DateRange[] = [
    {
      key: "updated",
      after: query.updated_after,
      before: query.updated_before,
      since: "updated.since",
      until: "updated.before",
      between: "updated.between",
    },
    {
      key: "created",
      after: query.created_after,
      before: query.created_before,
      since: "created.since",
      until: "created.before",
      between: "created.between",
    },
    {
      key: "sent",
      after: query.sent_after,
      before: query.sent_before,
      since: "sent.since",
      until: "sent.before",
      between: "sent.between",
    },
  ];
  for (const range of ranges) {
    const after = text(range.after);
    const before = text(range.before);
    const start = after ? formatQueryDate(after, locale) : null;
    const end = before ? formatQueryDate(before, locale) : null;
    if (start && end) add(range.key, range.between, { start, end });
    else if (start) add(range.key, range.since, { date: start });
    else if (end) add(range.key, range.until, { date: end });
  }

  const owner = text(query.owned_by);
  if (owner) add("owner", "owner", { owner });
  const folder = text(query.parent_hierarchy_node_id) ?? text(query.parent_id);
  if (folder) add("folder", "folder", { name: folderName || folder });
  const nodeType = text(query.node_type);
  if (nodeType) add("node_type", "nodeType", { type: nodeType });
  const author = text(query.message_type);
  if (author) add("author", "author", { author });
  const message = text(query.chat_message_id);
  if (message) add("message", "message", { id: message });
  if (query.cited_only === false) add("cited_only", "allRetrieved");

  if (query.count === true) {
    add("count", GROUP_LABELS[text(query.group_by) ?? ""] ?? "count");
  }
  if (text(query.cursor)) add("cursor", "nextPage");

  return chips;
}
