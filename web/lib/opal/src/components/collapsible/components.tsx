"use client";

import "@opal/components/collapsible/styles.css";
import { useCallback, useId, useState } from "react";
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgExpand, SvgFold } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import type { RichStr } from "@opal/types";

interface CollapsibleProps {
  /** Header title. */
  title: string | RichStr;
  /** Header description, under the title. */
  description?: string | RichStr;
  /** Rendered in the header, left of the collapse button. */
  rightChildren?: React.ReactNode;
  /** Controlled open state. */
  open?: boolean;
  /** Uncontrolled initial open state. @default false */
  defaultOpen?: boolean;
  /** Called with the next state when the fold toggles. */
  onOpenChange?: (open: boolean) => void;
  /**
   * The folded content. Stays mounted while closed, inert and hidden from
   * assistive tech, so the fold animates both ways.
   */
  children?: React.ReactNode;
  /** Ref forwarded to the root `<div>`. */
  ref?: React.Ref<HTMLDivElement>;
}

/**
 * A titled section that folds its content away. The header is a `Content`
 * wrapped in a `<label>` for the collapse button, so a click on the title or
 * description toggles the fold through that one control; `rightChildren`
 * sits outside the label and keeps its own clicks.
 */
function Collapsible({
  title,
  description,
  rightChildren,
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  children,
  ref,
}: CollapsibleProps) {
  const strings = useOpalStrings();
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : internalOpen;
  const buttonId = useId();

  const toggle = useCallback(() => {
    const next = !isOpen;
    if (!isControlled) setInternalOpen(next);
    onOpenChange?.(next);
  }, [isOpen, isControlled, onOpenChange]);

  return (
    <div ref={ref} className="opal-collapsible" data-open={isOpen}>
      <div className="opal-collapsible-header">
        <label htmlFor={buttonId} className="opal-collapsible-label">
          <Content
            title={title}
            description={description}
            sizePreset="main-content"
            variant="section"
          />
        </label>
        <div className="opal-collapsible-actions">
          {rightChildren}
          <Button
            id={buttonId}
            icon={isOpen ? SvgFold : SvgExpand}
            prominence="tertiary"
            aria-label={
              isOpen ? strings.collapsibleCollapse : strings.collapsibleExpand
            }
            onClick={toggle}
          />
        </div>
      </div>
      <div
        className="opal-collapsible-fold"
        data-open={isOpen}
        aria-hidden={!isOpen || undefined}
        inert={!isOpen || undefined}
      >
        <div className="opal-collapsible-fold-inner">{children}</div>
      </div>
    </div>
  );
}

export { Collapsible, type CollapsibleProps };
