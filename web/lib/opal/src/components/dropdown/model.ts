import type {
  DropdownItem,
  DropdownOption,
  DropdownRow,
  DropdownView,
  NavItem,
  RowGroup,
} from "@opal/components/dropdown/types";

/** What identifies a row: an option's value, any other row's id. */
export function rowKey(row: DropdownRow): string {
  return `${row.kind}:${row.kind === "option" ? row.value : row.id}`;
}

/** Groups the items for rendering: each group is a run, each stretch of loose rows one too. */
export function normalizeItems(
  items: readonly DropdownItem[] = []
): RowGroup[] {
  const groups: RowGroup[] = [];
  let looseRun: RowGroup | null = null;
  // A titled group is keyed by its title and its rank among same-titled
  // groups, so its fold state survives groups arriving or leaving elsewhere
  // in the list. Only titled groups fold; a loose run's key is its position.
  const titleCounts = new Map<string, number>();
  for (const entry of items) {
    if (entry.kind === "group") {
      const rank = titleCounts.get(entry.title ?? "") ?? 0;
      titleCounts.set(entry.title ?? "", rank + 1);
      groups.push({
        key:
          entry.title !== undefined
            ? `${entry.title}#${rank}`
            : String(groups.length),
        title: entry.title,
        rows: entry.items,
        foldable: entry.foldable,
      });
      looseRun = null;
      continue;
    }
    if (looseRun) {
      looseRun.rows.push(entry);
    } else {
      looseRun = { key: String(groups.length), rows: [entry] };
      groups.push(looseRun);
    }
  }
  return groups;
}

/** Flat row list in render order. */
export function flattenGroups(groups: RowGroup[]): DropdownRow[] {
  return groups.flatMap((group) => group.rows);
}

export function isOption(row: DropdownRow): row is DropdownOption {
  return row.kind === "option";
}

export function buildNavItems(
  groups: RowGroup[],
  createText?: string
): NavItem[] {
  const items: NavItem[] = [];
  if (createText !== undefined)
    items.push({ kind: "create", text: createText });
  for (const group of groups) {
    if (group.foldable && group.title !== undefined) {
      items.push({ kind: "group", group });
    }
    if (group.folded) continue;
    for (const row of group.rows) items.push({ kind: "row", row, group });
  }
  return items;
}

/** Whether the search term matches an option's title, value or keywords. */
export function optionMatchesSearch(
  option: Pick<DropdownOption, "title" | "value" | "keywords">,
  searchTerm: string
): boolean {
  return (
    option.title.toLowerCase().includes(searchTerm) ||
    option.value.toLowerCase().includes(searchTerm) ||
    keywordsMatch(option.keywords, searchTerm)
  );
}

function keywordsMatch(
  keywords: string[] | undefined,
  searchTerm: string
): boolean {
  return (
    keywords?.some((keyword) => keyword.toLowerCase().includes(searchTerm)) ??
    false
  );
}

/**
 * Whether the search term matches a row: an option by title, value or
 * keywords; an action or toggle by title or keywords; a custom row by its
 * keywords alone, since the dropdown cannot read what it shows.
 */
export function rowMatchesSearch(
  row: DropdownRow,
  searchTerm: string
): boolean {
  if (row.kind === "option") return optionMatchesSearch(row, searchTerm);
  if (row.kind === "custom") return keywordsMatch(row.keywords, searchTerm);
  return (
    row.title.toLowerCase().includes(searchTerm) ||
    keywordsMatch(row.keywords, searchTerm)
  );
}

/**
 * Filters each group's rows by the search term. A term that matches a
 * group's title keeps the whole group. Groups left empty disappear, so no
 * divider dangles.
 */
export function filterGroups(groups: RowGroup[], query: string): RowGroup[] {
  const searchTerm = query.trim().toLowerCase();
  if (!searchTerm) return groups.filter((g) => g.rows.length > 0);
  return groups
    .map((group) =>
      group.title?.toLowerCase().includes(searchTerm)
        ? group
        : {
            ...group,
            rows: group.rows.filter((row) => rowMatchesSearch(row, searchTerm)),
          }
    )
    .filter((group) => group.rows.length > 0);
}

/** Whether `text` equals an option's value or title, ignoring case and edges. */
export function optionMatchesExactly(
  option: Pick<DropdownOption, "title" | "value">,
  text: string
): boolean {
  const needle = text.trim().toLowerCase();
  if (!needle) return false;
  return (
    option.value.toLowerCase() === needle ||
    option.title.toLowerCase() === needle
  );
}

/** A value made safe for an element id: spaces and symbols are encoded. */
export function sanitizeId(value: string): string {
  return encodeURIComponent(value);
}

/** A row's element id, namespaced by kind: an option's value and an action's id never collide. */
export function rowElementId(listId: string, row: DropdownRow): string {
  return `${listId}-${row.kind}-${sanitizeId(rowKey(row))}`;
}

export function groupElementId(listId: string, key: string): string {
  return `${listId}-group-${sanitizeId(key)}`;
}

/** A view's key on the stack: its own, or its depth. */
export function viewKey(view: DropdownView, depth: number): string {
  return view.key !== undefined ? `key:${view.key}` : `depth:${depth}`;
}

/** The create row's id: its own namespace, so it never collides with an option. */
export function createElementId(listId: string): string {
  return `${listId}-create`;
}

/** The element id of a keyboard stop, for `aria-activedescendant`. */
export function navItemElementId(
  listId: string,
  item: NavItem | undefined
): string | undefined {
  if (!item) return undefined;
  if (item.kind === "row") return rowElementId(listId, item.row);
  if (item.kind === "create") return createElementId(listId);
  return item.group.title === undefined
    ? undefined
    : groupElementId(listId, item.group.key);
}
