"use client";

import { useEffect, useRef, type ReactNode, type Ref } from "react";
import { Button, Card, Popover, SelectButton } from "@opal/components";
import { SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";

export interface RunDetailsHintProps {
  icon: IconFunctionComponent;
  label: string;
  /** Whether its details are open. The open hint shows selected. Null for a hint that opens elsewhere, which has no expanded state. */
  open: boolean | null;
  onClick?: () => void;
  ref?: Ref<HTMLElement>;
}

/** A run's stage or checks hint. The rest of its props reach the button, so it can sit inside a `Popover.Trigger asChild`, whose own `aria-expanded` then wins. */
export function RunDetailsHint({
  icon,
  label,
  open,
  ...rest
}: RunDetailsHintProps) {
  return (
    <SelectButton
      icon={icon}
      variant="select-light"
      state={open ? "selected" : "empty"}
      size="xs"
      tooltip={label}
      aria-label={label}
      aria-expanded={open ?? undefined}
      {...rest}
    />
  );
}

export interface DetailsCloseButtonProps {
  label: string;
  /** Closes an inline card. Unset, it closes the enclosing Popover. */
  onClose?: () => void;
}

/** The close button of a run's details. An inline card takes focus on it as it opens, and a popover keeps its compact close. */
export function DetailsCloseButton({
  label,
  onClose,
}: DetailsCloseButtonProps) {
  const ref = useRef<HTMLElement>(null);
  const inline = onClose !== undefined;
  // Opening a card moves focus into it, as opening a popover did.
  useEffect(() => {
    if (inline) ref.current?.focus();
  }, [inline]);
  if (onClose === undefined) {
    return (
      <Popover.Close asChild>
        <Button
          icon={SvgX}
          prominence="tertiary"
          size="xs"
          aria-label={label}
        />
      </Popover.Close>
    );
  }
  return (
    <Button
      icon={SvgX}
      prominence="tertiary"
      size="md"
      aria-label={label}
      onClick={onClose}
      ref={ref}
    />
  );
}

export interface InlineDetailsCardProps {
  label: string;
  onClose: () => void;
  children: ReactNode;
}

/** A run's details in a card directly under its line. Escape closes it, as it closed the popover these cards replace. */
export function InlineDetailsCard({
  label,
  onClose,
  children,
}: InlineDetailsCardProps) {
  return (
    <Card
      padding={1}
      shadow="md"
      role="region"
      aria-label={label}
      data-testid="inline-details"
      onKeyDown={(event) => {
        if (event.key === "Escape") onClose();
      }}
    >
      {children}
    </Card>
  );
}
