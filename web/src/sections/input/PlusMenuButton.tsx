"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  LineItemButton,
  type DropdownMenuItem,
  type DropdownMenuRow,
  type DropdownView,
} from "@opal/components";
import { SvgChevronLeft, SvgPlus } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export interface PlusMenuFlyoutItem {
  key: string;
  label: string;
  icon?: IconFunctionComponent;
  description?: string;
  rightContent?: ReactNode;
  onSelect: () => void;
}

/** A direct-action row (`onSelect`) or a flyout row (`flyoutItems`). */
export interface PlusMenuItem {
  key: string;
  label: string;
  icon: IconFunctionComponent;
  onSelect?: () => void;
  flyoutItems?: PlusMenuFlyoutItem[];
}

export interface PlusMenuButtonProps {
  /** Menu rows. A `null` entry renders as a divider. */
  items: Array<PlusMenuItem | null>;
  disabled?: boolean;
  tooltip?: string;
  ariaLabel?: string;
}

/** A flyout's sub-rows: custom rows, since `rightContent` is a node. */
function flyoutRow(sub: PlusMenuFlyoutItem): DropdownMenuRow {
  return {
    kind: "custom",
    id: sub.key,
    keywords: [sub.label],
    onActivate: sub.onSelect,
    render: ({ highlighted, props }) => (
      <LineItemButton
        presentational
        selectVariant="select-heavy"
        interaction={highlighted ? "hover" : "rest"}
        rounding={2}
        sizePreset="main-ui"
        variant="section"
        icon={sub.icon}
        title={sub.label}
        description={sub.description}
        rightChildren={sub.rightContent}
        {...props}
      />
    ),
  };
}

/**
 * A flyout row leads to a view of its own, in place of the menu; the view's
 * first row leads back. Views open on a click or Enter.
 */
export function PlusMenuButton({
  items,
  disabled = false,
  tooltip,
  ariaLabel,
}: PlusMenuButtonProps) {
  const t = useTranslations("chat.input");
  const [open, setOpen] = useState(false);

  const views: Record<string, DropdownView> = {};
  const menuItems: DropdownMenuItem[] = [];
  let group: DropdownMenuRow[] = [];
  const groups: DropdownMenuRow[][] = [group];
  for (const item of items) {
    // A `null` entry is a line between groups.
    if (item === null) {
      group = [];
      groups.push(group);
      continue;
    }
    if (item.flyoutItems) {
      views[item.key] = {
        items: [
          {
            kind: "action",
            id: "back",
            icon: SvgChevronLeft,
            title: item.label,
            onSelect: (stack) => stack.pop(),
          },
          ...item.flyoutItems.map(flyoutRow),
        ],
      };
      // The row that leads to the flyout's page.
      group.push({
        kind: "action",
        id: item.key,
        icon: item.icon,
        title: item.label,
        onSelect: (stack) => stack.push(item.key),
      });
      continue;
    }
    group.push({
      kind: "action",
      id: item.key,
      icon: item.icon,
      title: item.label,
      onSelect: () => item.onSelect?.(),
    });
  }
  const filled = groups.filter((rows) => rows.length > 0);
  if (filled.length === 1 && filled[0]) menuItems.push(...filled[0]);
  else
    for (const rows of filled) menuItems.push({ kind: "group", items: rows });

  return (
    <Dropdown open={open} onOpenChange={setOpen}>
      <Dropdown.Trigger asChild>
        <Button
          icon={SvgPlus}
          prominence="tertiary"
          disabled={disabled}
          tooltip={tooltip ?? t("plusMenuButton.trigger.tooltip")}
          aria-label={ariaLabel ?? t("plusMenuButton.trigger.ariaLabel")}
        />
      </Dropdown.Trigger>
      <Dropdown.Data
        label={ariaLabel ?? t("plusMenuButton.trigger.ariaLabel")}
        items={menuItems}
        views={views}
      />
    </Dropdown>
  );
}

export default PlusMenuButton;
