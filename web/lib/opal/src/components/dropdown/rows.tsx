"use client";

import React from "react";
import { LineItemButton } from "@opal/components/buttons/line-item-button/components";
import { InputSwitch } from "@opal/components/inputs/booleans/input-switch/components";
import { Text } from "@opal/components/text/components";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { isRichNodes } from "@opal/utils";
import { rowElementId } from "@opal/components/dropdown/model";
import type { TextFont } from "@opal/components/text/components";
import type {
  DropdownMode,
  DropdownRow,
  DropdownRowProps,
  DropdownSizePreset,
} from "@opal/components/dropdown/types";

/**
 * Whether the pointer's target is a control that needs focus to work (an
 * input inside a custom row, or the search field). Focus stays there;
 * anywhere else a press gives focus back to where it was.
 */
export function targetTakesFocus(event: React.MouseEvent): boolean {
  return (
    event.target instanceof Element &&
    event.target.closest("input, textarea, select, [contenteditable]") !== null
  );
}

/** Whether the user has text selected: a drag or a double-click on text. */
export function selectsText(): boolean {
  const selection = window.getSelection();
  return selection !== null && !selection.isCollapsed;
}

interface RowProps {
  listId: string;
  mode: DropdownMode;
  row: DropdownRow;
  sizePreset: DropdownSizePreset;
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
  sizePreset,
  index,
  isHighlighted,
  isSelected,
  onActivate,
}: RowProps) {
  const id = rowElementId(listId, row);
  const interaction = isHighlighted ? "hover" : "rest";
  const onClick = (event: React.MouseEvent) => {
    event.stopPropagation();
    // A drag that selected text is not a pick.
    if (selectsText()) return;
    if (!row.disabled) onActivate(row);
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
        font={
          row.description
            ? sizePreset === "secondary"
              ? "secondary-action"
              : "main-ui-action"
            : sizePreset === "secondary"
              ? "secondary-body"
              : "main-ui-body"
        }
        padding={sizePreset === "secondary" ? 0 : 0.5}
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
      />
    );
  }

  // A linked option is already an <a>, so its note shows markdown links as
  // plain text; an anchor must not hold another.
  const info =
    row.kind === "option" &&
    row.href !== undefined &&
    row.info !== undefined &&
    !isRichNodes(row.info)
      ? toPlainString(row.info)
      : row.kind === "option"
        ? row.info
        : undefined;

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
    badge: row.kind === "option" ? row.tag : undefined,
    rightChildren: info ? (
      <div className="opal-dropdown-info">
        <Text
          as="p"
          font="secondary-body"
          color="inherit"
          textPosition="text-end"
          wordWrap="wrap-anywhere"
        >
          {info}
        </Text>
      </div>
    ) : undefined,
    descriptionMaxLines:
      row.kind === "option" ? row.descriptionMaxLines : undefined,
    color: row.kind === "action" && row.danger ? "error" : undefined,
    titleColor: row.kind === "action" && row.danger ? "text-03" : undefined,
    tooltip:
      row.kind === "action" || row.kind === "option" ? row.tooltip : undefined,
    // Beside the list, so it never covers the row above.
    tooltipSide: "end",
    padding: sizePreset === "secondary" ? 0 : 0.5,
    // A row with a description, suffix or badge sets its title in the
    // action weight; a bare row in the body weight.
    font: (row.description || (row.kind === "option" && (row.suffix || row.tag))
      ? sizePreset === "secondary"
        ? "secondary-action"
        : "main-ui-action"
      : sizePreset === "secondary"
        ? "secondary-body"
        : "main-ui-body") satisfies TextFont,
    id,
    "data-index": index,
    role: mode === "picker" ? "option" : "menuitem",
    ...(mode === "picker" && { "aria-selected": isSelected }),
    tabIndex: -1,
    onClick,
  } as const;

  if (row.kind === "action" && row.href !== undefined) {
    // A real link: the click navigates natively, and Enter clicks it, so
    // middle-click, modifier-click and copy-link work.
    return <LineItemButton {...content} href={row.href} target={row.target} />;
  }
  if (row.kind === "option" && row.href !== undefined) {
    // A link among the options, the same way.
    return <LineItemButton {...content} href={row.href} />;
  }
  return <LineItemButton presentational {...content} />;
});
