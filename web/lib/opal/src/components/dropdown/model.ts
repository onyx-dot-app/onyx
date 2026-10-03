import type {
  DropdownItem,
  DropdownOption,
  NavItem,
  OptionGroup,
} from "@opal/components/dropdown/types";

/** Groups the items for rendering: each group is a run, each stretch of loose options one too. */
export function normalizeItems(items: DropdownItem[] = []): OptionGroup[] {
  const groups: OptionGroup[] = [];
  let looseRun: OptionGroup | null = null;
  for (const entry of items) {
    if (entry.kind === "group") {
      groups.push({
        title: entry.title,
        options: entry.items,
        foldable: entry.foldable,
      });
      looseRun = null;
      continue;
    }
    if (looseRun) {
      looseRun.options.push(entry);
    } else {
      looseRun = { options: [entry] };
      groups.push(looseRun);
    }
  }
  return groups;
}

/** Flat option list in render order. */
export function flattenGroups(groups: OptionGroup[]): DropdownOption[] {
  return groups.flatMap((group) => group.options);
}

export function buildNavItems(
  groups: OptionGroup[],
  createText?: string
): NavItem[] {
  const items: NavItem[] = [];
  if (createText !== undefined) items.push({ kind: "create", text: createText });
  for (const group of groups) {
    if (group.foldable && group.title !== undefined) {
      items.push({ kind: "group", group });
    }
    if (group.folded) continue;
    for (const option of group.options) items.push({ kind: "option", option });
  }
  return items;
}

/** Whether the search term matches a row's title, value or keywords. */
export function optionMatchesSearch(
  option: Pick<DropdownOption, "title" | "value" | "keywords">,
  searchTerm: string
): boolean {
  return (
    option.title.toLowerCase().includes(searchTerm) ||
    option.value.toLowerCase().includes(searchTerm) ||
    (option.keywords?.some((keyword) =>
      keyword.toLowerCase().includes(searchTerm)
    ) ??
      false)
  );
}

/**
 * Filters each group's options by the search term, matched against a row's
 * title, value or keywords. A term that matches a group's title keeps the
 * whole group. Groups left empty disappear, so no divider dangles.
 */
export function filterGroups(
  groups: OptionGroup[],
  query: string
): OptionGroup[] {
  const searchTerm = query.trim().toLowerCase();
  if (!searchTerm) return groups.filter((g) => g.options.length > 0);
  return groups
    .map((group) =>
      group.title?.toLowerCase().includes(searchTerm)
        ? group
        : {
            ...group,
            options: group.options.filter((option) =>
              optionMatchesSearch(option, searchTerm)
            ),
          }
    )
    .filter((group) => group.options.length > 0);
}

/** Whether `text` equals a row's value or title, ignoring case and edges. */
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

export function optionElementId(listId: string, value: string): string {
  return `${listId}-option-${sanitizeId(value)}`;
}

export function groupElementId(listId: string, title: string): string {
  return `${listId}-group-${sanitizeId(title)}`;
}

/** The element id of a keyboard stop, for `aria-activedescendant`. */
export function navItemElementId(
  listId: string,
  item: NavItem | undefined
): string | undefined {
  if (!item) return undefined;
  if (item.kind === "option") return optionElementId(listId, item.option.value);
  if (item.kind === "create") return optionElementId(listId, item.text);
  return item.group.title === undefined
    ? undefined
    : groupElementId(listId, item.group.title);
}
