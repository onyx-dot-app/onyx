"use client";

import { useTranslations } from "next-intl";
import { InputTypeIn } from "@opal/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import type { RichStr } from "@opal/types";
import { escapeMarkdown, markdown } from "@opal/utils";
import { IllustrationContent, PageCenter } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import SvgEmpty from "@opal/illustrations/empty";
import type { UseSearchableGridReturn } from "@opal/hooks";

// Stands in for the subject while the translated sentence is built, so a
// markdown subject can be put back in without the sentence's own text being
// read as markdown.
const SUBJECT = "\u0000";

/**
 * A title that names its subject: plain when the subject is plain, else
 * markdown with the subject kept as given and the rest escaped.
 */
function titleWithSubject(
  item: string | RichStr,
  build: (subject: string) => string
): string | RichStr {
  if (typeof item === "string") return build(item);
  return markdown(
    build(SUBJECT)
      .split(SUBJECT)
      .map((part) => escapeMarkdown(part))
      .join(item.raw)
  );
}

// ---------------------------------------------------------------------------
// NoResults
// ---------------------------------------------------------------------------

export interface NoResultsProps {
  /** What the list holds, as a plural noun ("agents"): "No agents found". */
  item?: string | RichStr;
}

/**
 * A list whose search or filters match nothing. While the search field holds
 * text, show it even when the list has no items at all; otherwise use
 * `NoItems` for an empty list.
 */
export function NoResults({ item }: NoResultsProps) {
  const t = useTranslations("common.states.noResults");
  return (
    <PageCenter>
      <IllustrationContent
        illustration={SvgNoResult}
        title={
          item === undefined
            ? t("title")
            : titleWithSubject(item, (subject) =>
                t("itemTitle", { item: subject })
              )
        }
        description={t("description")}
      />
    </PageCenter>
  );
}

// ---------------------------------------------------------------------------
// NoItems
// ---------------------------------------------------------------------------

export interface NoItemsProps {
  /** What the list holds, as a plural noun ("agents"): "No agents". */
  item?: string | RichStr;
  /** Below the title: what the list would hold, or how to add the first item. */
  description: string | RichStr;
}

/** A list with no items at all, and no search typed. */
export function NoItems({ item, description }: NoItemsProps) {
  const t = useTranslations("common.states.noItems");
  return (
    <PageCenter>
      <IllustrationContent
        illustration={SvgEmpty}
        title={
          item === undefined
            ? t("title")
            : titleWithSubject(item, (subject) =>
                t("itemTitle", { item: subject })
              )
        }
        description={description}
      />
    </PageCenter>
  );
}

// ---------------------------------------------------------------------------
// GridSearchInput
// ---------------------------------------------------------------------------

export interface GridSearchInputProps {
  /** From `useSearchableGrid`, which owns the keyboard behavior. */
  search: UseSearchableGridReturn;
  value: string;
  onChange: (value: string) => void;
  /**
   * What the grid holds, as a plural noun, for the placeholder: 'Search
   * agents or press "/" to focus...'. A placeholder shows plain text only, so
   * a markdown item contributes its text without the markup.
   */
  item?: string | RichStr;
}

/**
 * The search field of a searchable grid: focused on mount and on "/", linked
 * to the grid by the arrow keys (`useSearchableGrid`), with a clear (×) button
 * while it holds text.
 */
export function GridSearchInput({
  search,
  value,
  onChange,
  item,
}: GridSearchInputProps) {
  const t = useTranslations("common.gridSearch");
  const placeholder =
    item === undefined
      ? t("placeholder")
      : t("itemPlaceholder", {
          item: toPlainString(item),
        });
  return (
    <InputTypeIn
      ref={search.inputRef}
      icon="search"
      clearButton
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={search.onSearchKeyDown}
    />
  );
}
