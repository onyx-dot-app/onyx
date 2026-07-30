"use client";

import { LineItemButton, OpenButton, Popover } from "@opal/components";
import { SvgMinusCircle } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export interface SharePermissionMenuOption<T extends string> {
  value: T;
  label: string;
  icon: IconFunctionComponent;
}

export interface SharePermissionMenuProps<T extends string> {
  value: T;
  options: SharePermissionMenuOption<T>[];
  onChange?: (value: T) => void;
  onRemove?: () => void;
  removeLabel?: string;
  disabled?: boolean;
  width?: "fit" | "full";
  /** The status row's qualifier already shows the scope icon — the mock's
      scope pill is text + chevron only */
  showTriggerIcon?: boolean;
  /** Fixed menu width — full-width items inside a fit-content popover
      collapse to min-content and truncate */
  menuWidth?: "sm" | "md" | "lg" | "xl" | "2xl";
  ariaLabel?: string;
}

export function SharePermissionMenu<T extends string>({
  value,
  options,
  onChange,
  onRemove,
  removeLabel = "Remove Access",
  disabled = false,
  width = "fit",
  showTriggerIcon = true,
  menuWidth = "md",
  ariaLabel,
}: SharePermissionMenuProps<T>) {
  const selectedOption =
    options.find((option) => option.value === value) ?? options[0];

  if (!selectedOption) {
    return null;
  }

  if (disabled || (!onChange && !onRemove)) {
    return (
      <OpenButton
        aria-label={ariaLabel}
        disabled
        foldable={false}
        icon={showTriggerIcon ? selectedOption.icon : undefined}
        labelColor="text-04"
        labelFont="main-ui-action"
        size="sm"
        variant="select-light"
        width={width}
      >
        {selectedOption.label}
      </OpenButton>
    );
  }

  return (
    <Popover>
      <Popover.Trigger asChild>
        <OpenButton
          aria-label={ariaLabel}
          foldable={false}
          icon={showTriggerIcon ? selectedOption.icon : undefined}
          labelColor="text-04"
          labelFont="main-ui-action"
          size="sm"
          variant="select-light"
          width={width}
        >
          {selectedOption.label}
        </OpenButton>
      </Popover.Trigger>

      <Popover.Content align="end" side="bottom" width={menuWidth}>
        <Popover.Menu>
          {options.map((option) => (
            <Popover.Close asChild key={option.value}>
              <LineItemButton
                icon={option.icon}
                onClick={() => onChange?.(option.value)}
                rounding="md"
                selectVariant="select-heavy"
                sizePreset="main-ui"
                state={option.value === value ? "selected" : "empty"}
                title={option.label}
                variant="section"
                width="full"
              />
            </Popover.Close>
          ))}

          {onRemove && (
            <Popover.Close asChild>
              <LineItemButton
                color="danger"
                icon={SvgMinusCircle}
                onClick={onRemove}
                rounding="md"
                selectVariant="select-heavy"
                sizePreset="main-ui"
                title={removeLabel}
                variant="section"
                width="full"
              />
            </Popover.Close>
          )}
        </Popover.Menu>
      </Popover.Content>
    </Popover>
  );
}
