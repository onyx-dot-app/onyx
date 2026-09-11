"use client";

import "@opal/components/inputs/input-multi-select/styles.css";
import React, { useMemo, useRef, useState } from "react";
import type {
  IconFunctionComponent,
  RichStr,
  WithoutStyles,
} from "@opal/types";
import {
  Card,
  EmptyMessageCard,
  InputTypeIn,
  LineItemButton,
  Popover,
  ShadowDiv,
} from "@opal/components";
import { SvgCheck, SvgX } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { toPlainString } from "@opal/components/text/InlineMarkdown";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InputMultiSelectItem {
  id: string;

  /** Main label; also what the search filters on. */
  title: string | RichStr;

  /** Caller-formatted metadata under the title, e.g. a member count. */
  description?: string | RichStr;

  /** Leading icon. Selected dropdown rows show a check instead. */
  icon?: IconFunctionComponent;
}

/**
 * `value`/`onChange`/`disabled` are owned by this component's contract and
 * `children` has no meaning for it; everything else a caller passes that is
 * not listed below is DOM and reaches the search input (so `data-*` hooks
 * land on the element tests actually drive).
 */
type InputMultiSelectProps = Omit<
  WithoutStyles<React.InputHTMLAttributes<HTMLInputElement>>,
  "value" | "onChange" | "disabled" | "children"
> & {
  /** Full option set; the component filters it by title as the user types. */
  items: InputMultiSelectItem[];

  /** Selected item ids — fully controlled. */
  value: string[];

  /** Called with the next selected-id set on every toggle or removal. */
  onChange: (next: string[]) => void;

  /** Placeholder for the search input. */
  placeholder?: string;

  /** Disables the search input, the dropdown, and every row. */
  disabled?: boolean;

  /**
   * Trailing icon on selected-list rows; clicking the row removes the item.
   *
   * @default SvgX
   */
  removeIcon?: IconFunctionComponent;

  /** Portal container for the dropdown (e.g. a modal's content element). */
  container?: HTMLElement | null;
};

// ---------------------------------------------------------------------------
// InputMultiSelect
// ---------------------------------------------------------------------------

/**
 * Searchable multi-select: a search input opens a dropdown of options, and
 * the current selection lives in a list below it. Clicking a dropdown row
 * toggles it; clicking a selected row removes it.
 *
 * Controlled only — pair it with `InputMultiSelectField` from `@opal/form`
 * inside a Formik form.
 */
function InputMultiSelect({
  items,
  value,
  onChange,
  placeholder,
  disabled,
  removeIcon: RemoveIcon = SvgX,
  container,
  onFocus,
  onClick,
  ...inputProps
}: InputMultiSelectProps) {
  const strings = useOpalStrings();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const anchorRef = useRef<HTMLDivElement>(null);

  const selectedIds = useMemo(() => new Set(value), [value]);
  const selectedItems = useMemo(
    () => items.filter((item) => selectedIds.has(item.id)),
    [items, selectedIds]
  );

  const filteredItems = useMemo(() => {
    const trimmed = query.trim().toLowerCase();
    if (!trimmed) return items;
    return items.filter((item) =>
      toPlainString(item.title).toLowerCase().includes(trimmed)
    );
  }, [items, query]);

  function toggle(id: string) {
    onChange(
      selectedIds.has(id)
        ? value.filter((selected) => selected !== id)
        : [...value, id]
    );
  }

  return (
    <Card color="background-tint-01" padding={1.5} rounding={3}>
      <Popover
        open={!disabled && open}
        onOpenChange={(next) => !disabled && setOpen(next)}
      >
        {/* Anchor, not Trigger: a trigger moves focus into the content on
            open and toggles closed when the input is clicked again. The
            input opens the dropdown on focus and keeps the caret. */}
        <Popover.Anchor asChild>
          <div ref={anchorRef}>
            <InputTypeIn
              {...inputProps}
              searchIcon
              placeholder={placeholder}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onFocus={(e) => {
                setOpen(true);
                onFocus?.(e);
              }}
              onClick={(e) => {
                setOpen(true);
                onClick?.(e);
              }}
              variant={disabled ? "disabled" : undefined}
            />
          </div>
        </Popover.Anchor>
        <Popover.Content
          width="trigger"
          align="start"
          container={container}
          onOpenAutoFocus={(e) => e.preventDefault()}
          onInteractOutside={(e) => {
            if (anchorRef.current?.contains(e.target as Node)) {
              e.preventDefault();
            }
          }}
        >
          <ShadowDiv
            shadowHeight="0.75rem"
            className="opal-input-multi-select-dropdown"
          >
            {filteredItems.map((item) => {
              const selected = selectedIds.has(item.id);
              return (
                <LineItemButton
                  key={item.id}
                  sizePreset="main-ui"
                  variant="section"
                  icon={selected ? SvgCheck : item.icon}
                  title={item.title}
                  titleMaxLines={1}
                  description={item.description}
                  descriptionMaxLines={1}
                  state={selected ? "selected" : undefined}
                  selectVariant="select-heavy"
                  rounding={2}
                  onClick={() => toggle(item.id)}
                />
              );
            })}
          </ShadowDiv>
        </Popover.Content>
      </Popover>

      <ShadowDiv
        shadowHeight="0.75rem"
        className="opal-input-multi-select-selected"
      >
        {selectedItems.length === 0 ? (
          <EmptyMessageCard
            sizePreset="main-ui"
            padding={2}
            title={strings.multiSelectEmptyTitle}
            description={strings.multiSelectEmptyDescription}
          />
        ) : (
          selectedItems.map((item) => (
            <div key={item.id} className="opal-input-multi-select-row">
              <LineItemButton
                sizePreset="main-ui"
                variant="section"
                icon={item.icon}
                title={item.title}
                titleMaxLines={1}
                description={item.description}
                descriptionMaxLines={1}
                disabled={disabled}
                rightChildren={<RemoveIcon height={16} width={16} />}
                onClick={() => toggle(item.id)}
              />
            </div>
          ))
        )}
      </ShadowDiv>
    </Card>
  );
}

export {
  InputMultiSelect,
  type InputMultiSelectProps,
  type InputMultiSelectItem,
};
