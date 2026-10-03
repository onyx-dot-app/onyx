"use client";

import React from "react";
import { LineItemButton } from "@opal/components/buttons/line-item-button/components";
import { InputSwitch } from "@opal/components/inputs/booleans/input-switch/components";
import { rowElementId, rowKey } from "@opal/components/dropdown/model";
import type {
  DropdownMode,
  DropdownRow,
  DropdownRowProps,
} from "@opal/components/dropdown/types";

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
 * as the selected state and the keyboard stop as hover. Memoized: the list
 * re-renders on every highlight move.
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
  const id = rowElementId(listId, rowKey(row));
  const interaction = isHighlighted ? "hover" : "rest";
  const onClick = (event: React.MouseEvent) => {
    event.stopPropagation();
    if (!row.disabled) onActivate(row);
  };
  // Keep focus on the trigger: the pick must not blur it.
  const onMouseDown = (event: React.MouseEvent) => {
    event.preventDefault();
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
          <span inert className="opal-dropdown-toggle">
            <InputSwitch checked={row.checked} />
          </span>
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

  const isAction = row.kind === "action";
  return (
    <LineItemButton
      presentational
      selectVariant="select-heavy"
      state={isSelected ? "selected" : "empty"}
      interaction={interaction}
      disabled={row.disabled}
      rounding={2}
      icon={row.icon}
      title={row.title}
      description={row.description}
      suffix={row.kind === "option" ? row.suffix : undefined}
      color={isAction && row.danger ? "danger" : undefined}
      sizePreset="main-ui"
      // `body` resolves to `ContentSm`, which has no description or suffix
      // slot; a row with either takes the `heading` layout.
      variant={
        row.description || (row.kind === "option" && row.suffix)
          ? "heading"
          : "body"
      }
      id={id}
      data-index={index}
      role={mode === "picker" ? "option" : "menuitem"}
      {...(mode === "picker" && { "aria-selected": isSelected })}
      tabIndex={-1}
      onClick={onClick}
      onMouseDown={onMouseDown}
    />
  );
});
