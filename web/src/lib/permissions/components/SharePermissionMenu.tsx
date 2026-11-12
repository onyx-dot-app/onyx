"use client";

import { useTranslations } from "next-intl";
import {
  Dropdown,
  RowAction,
  SelectButton,
  type DropdownItem,
  type DropdownWidth,
} from "@opal/components";
import { SvgMinusCircle } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export interface SharePermissionMenuOption<T extends string> {
  value: T;
  label: string;
  icon: IconFunctionComponent;
  /** What the permission allows, under its label in the list. */
  description?: string;
}

export interface SharePermissionMenuProps<T extends string> {
  value: T;
  options: SharePermissionMenuOption<T>[];
  onChange?: (value: T) => void;
  onRemove?: () => void;
  removeLabel?: string;
  disabled?: boolean;
  /** A fixed width for the open list. Left out, it follows the trigger. */
  menuWidth?: DropdownWidth;
  /** The status row's qualifier already shows the scope icon — the mock's
      scope pill is text + chevron only */
  showTriggerIcon?: boolean;
  ariaLabel?: string;
  /** `"row"` renders a full-width `RowAction` for a table cell: a
      chevron trigger when it can change, static text when it cannot. */
  layout?: "inline" | "row";
}

export default function SharePermissionMenu<T extends string>({
  value,
  options,
  onChange,
  onRemove,
  removeLabel,
  disabled = false,
  menuWidth,
  showTriggerIcon = true,
  ariaLabel,
  layout = "inline",
}: SharePermissionMenuProps<T>) {
  const t = useTranslations("chat.modals.share");
  const selectedOption =
    options.find((option) => option.value === value) ?? options[0];

  if (!selectedOption) {
    return null;
  }

  const triggerIcon = showTriggerIcon ? selectedOption.icon : undefined;

  if (disabled || (!onChange && !onRemove)) {
    if (layout === "row") {
      return (
        <RowAction aria-label={ariaLabel} icon={triggerIcon}>
          {selectedOption.label}
        </RowAction>
      );
    }
    return (
      <SelectButton
        chevron
        aria-label={ariaLabel}
        disabled
        foldable={false}
        icon={showTriggerIcon ? selectedOption.icon : undefined}
        labelColor="text-04"
        labelFont="main-ui-action"
        size="sm"
        variant="select-light"
      >
        {selectedOption.label}
      </SelectButton>
    );
  }

  // A picker with one command at its end: the options pick a scope, and
  // the danger row, set apart below a divider, removes access.
  const items: DropdownItem[] = [
    ...options.map(
      (option): DropdownItem => ({
        kind: "option",
        value: option.value,
        icon: option.icon,
        title: option.label,
        description: option.description,
      })
    ),
    // An untitled group draws a divider above the danger row.
    ...(onRemove
      ? [
          {
            kind: "group" as const,
            items: [
              {
                kind: "action" as const,
                id: "remove-access",
                icon: SvgMinusCircle,
                danger: true,
                title: removeLabel ?? t("permissionMenu.removeAccess.label"),
                onSelect: onRemove,
              },
            ],
          },
        ]
      : []),
  ];

  return (
    <Dropdown width={menuWidth}>
      <Dropdown.Trigger asChild>
        {layout === "row" ? (
          <RowAction chevron aria-label={ariaLabel} icon={triggerIcon}>
            {selectedOption.label}
          </RowAction>
        ) : (
          <SelectButton
            chevron
            aria-label={ariaLabel}
            foldable={false}
            icon={showTriggerIcon ? selectedOption.icon : undefined}
            labelColor="text-04"
            labelFont="main-ui-action"
            size="sm"
            variant="select-light"
          >
            {selectedOption.label}
          </SelectButton>
        )}
      </Dropdown.Trigger>
      <Dropdown.Data
        label={ariaLabel}
        value={value}
        onSelect={(option) => {
          const next = options.find((o) => o.value === option.value);
          if (next) onChange?.(next.value);
        }}
        items={items}
      />
    </Dropdown>
  );
}
