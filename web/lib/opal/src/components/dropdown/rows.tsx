"use client";

import React from "react";
import { Button } from "@opal/components/buttons/button/components";
import { LineItemButton } from "@opal/components/buttons/line-item-button/components";
import { InputSwitch } from "@opal/components/inputs/booleans/input-switch/components";
import { SvgChevronRight } from "@opal/icons";
import { rowElementId } from "@opal/components/dropdown/model";
import type {
  DropdownMode,
  DropdownRow,
  DropdownRowProps,
} from "@opal/components/dropdown/types";

/**
 * Whether a mousedown must keep its default: the target is a control that
 * needs focus to work (an input inside a custom row). Anything else keeps
 * focus on the trigger, so a pick never blurs it.
 */
export function targetTakesFocus(event: React.MouseEvent): boolean {
  return (
    event.target instanceof Element &&
    event.target.closest("input, textarea, select, [contenteditable]") !== null
  );
}

interface RowProps {
  listId: string;
  mode: DropdownMode;
  row: DropdownRow;
  /** The row's keyboard stop, or -1 while it is withheld (folded). */
  index: number;
  isHighlighted: boolean;
  /** An option that is picked, or an option the trigger text matches exactly. */
  isSelected: boolean;
  onActivate: (row: DropdownRow) => void;
}

/**
 * One row of the list, rendered by kind. Rows are presentational
 * `LineItemButton`s, since the list owns focus and the keyboard and
 * addresses the row through `aria-activedescendant`: the selection reads
 * as the selected state and the keyboard stop as hover. A link action is
 * the one native control, an anchor. Memoized: the list re-renders on every
 * highlight move.
 */
export const Row = React.memo(function Row({
  listId,
  mode,
  row,
  index,
  isHighlighted,
  isSelected,
  onActivate,
}: RowProps) {
  const id = rowElementId(listId, row);
  const interaction = isHighlighted ? "hover" : "rest";
  const onClick = (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!row.disabled) onActivate(row);
  };
  // Keep focus on the trigger: the pick must not blur it. A control inside
  // a custom row that needs focus keeps the default.
  const onMouseDown = (event: React.MouseEvent) => {
    if (!targetTakesFocus(event)) event.preventDefault();
  };

  if (row.kind === "custom") {
    const props: DropdownRowProps = {
      id,
      role: mode === "picker" ? "option" : "menuitem",
      ...(mode === "picker" && { "aria-selected": false }),
      ...(row.disabled && { "aria-disabled": true }),
      "data-index": index,
      tabIndex: -1,
      onClick,
      onMouseDown,
    };
    return <>{row.render({ highlighted: isHighlighted, props })}</>;
  }

  if (row.kind === "toggle") {
    return (
      <LineItemButton
        presentational
        selectVariant="select-heavy"
        interaction={interaction}
        disabled={row.disabled}
        rounding={2}
        icon={row.icon}
        title={row.title}
        description={row.description}
        sizePreset="main-ui"
        variant={row.description ? "heading" : "body"}
        // The switch only shows the state: the row is the control, so the
        // switch takes no pointer or focus of its own.
        rightChildren={
          <div inert className="opal-dropdown-toggle">
            <InputSwitch checked={row.checked} />
          </div>
        }
        id={id}
        data-index={index}
        role={mode === "picker" ? "option" : "menuitemcheckbox"}
        {...(mode === "picker"
          ? { "aria-selected": row.checked }
          : { "aria-checked": row.checked })}
        tabIndex={-1}
        onClick={onClick}
        onMouseDown={onMouseDown}
      />
    );
  }

  const content = {
    selectVariant: "select-heavy",
    state: isSelected ? "selected" : "empty",
    interaction,
    disabled: row.disabled,
    rounding: 2,
    icon: row.icon,
    title: row.title,
    description: row.description,
    suffix: row.kind === "option" ? row.suffix : undefined,
    color: row.kind === "action" && row.danger ? "danger" : undefined,
    // A row that leads to a view says so with a chevron button. It only
    // shows the way: the row is the control, so the button takes no
    // pointer or focus of its own.
    rightChildren:
      row.kind === "action" && row.opensView ? (
        <div inert className="opal-dropdown-chevron">
          <Button icon={SvgChevronRight} size="sm" prominence="internal" />
        </div>
      ) : undefined,
    sizePreset: "main-ui",
    // `body` resolves to `ContentSm`, which has no description or suffix
    // slot; a row with either takes the `heading` layout.
    variant:
      row.description || (row.kind === "option" && row.suffix)
        ? "heading"
        : "body",
    id,
    "data-index": index,
    role: mode === "picker" ? "option" : "menuitem",
    ...(mode === "picker" && { "aria-selected": isSelected }),
    tabIndex: -1,
    onClick,
    onMouseDown,
  } as const;

  if (row.kind === "action" && row.href !== undefined) {
    // A real link: the click navigates natively, and Enter clicks it, so
    // middle-click, modifier-click and copy-link work.
    return <LineItemButton {...content} href={row.href} target={row.target} />;
  }
  return <LineItemButton presentational {...content} />;
});
