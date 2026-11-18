"use client";

import "@opal/components/buttons/fold-button/styles.css";
import {
  Button,
  type ButtonProps,
} from "@opal/components/buttons/button/components";
import { SvgChevronRight } from "@opal/icons";
import type { ContainerSizeVariants, IconProps } from "@opal/types";
import { cn } from "@opal/utils";

interface FoldButtonProps {
  /** Whether the section it folds is open: the chevron turns down. */
  open: boolean;
  /** @default "sm" */
  size?: ContainerSizeVariants;
  onClick?: React.MouseEventHandler<HTMLElement>;
  tooltip?: string;
  "aria-label"?: string;
  "aria-hidden"?: boolean;
  /** `-1` keeps it out of the Tab order, for a header that is the control. */
  tabIndex?: number;
  /** @default "tertiary" */
  prominence?: ButtonProps["prominence"];
  /** Overrides the interaction state, e.g. to light up with its row. */
  interaction?: ButtonProps["interaction"];
  onFocus?: React.FocusEventHandler<HTMLElement>;
  onBlur?: React.FocusEventHandler<HTMLElement>;
  "aria-controls"?: string;
  /** Shows the control as unavailable and suppresses clicks. */
  disabled?: boolean;
}

/**
 * The chevron, marked so that only it turns, not the button around it. A
 * stable component, so the SVG never remounts and the turn animates.
 */
function FoldChevron({ className, ...props }: IconProps) {
  return (
    <SvgChevronRight
      className={cn(className, "opal-fold-chevron")}
      {...props}
    />
  );
}

/**
 * The fold control of a foldable row: a tertiary chevron that points right
 * while folded and turns down while open. `Divider`'s foldable header, a
 * timeline step and a connector check use it.
 */
function FoldButton({
  open,
  size = "sm",
  prominence = "tertiary",
  ...buttonProps
}: FoldButtonProps) {
  return (
    <span className="opal-fold-button" data-open={open}>
      <Button
        icon={FoldChevron}
        size={size}
        prominence={prominence}
        aria-expanded={open}
        {...buttonProps}
      />
    </span>
  );
}

export { FoldButton, type FoldButtonProps };
