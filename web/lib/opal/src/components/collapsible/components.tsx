"use client";

import "@opal/components/collapsible/styles.css";
import { useId, useState } from "react";
import type { RichStr } from "@opal/types";
import { ContentAction } from "@opal/layouts";
import { Button, type TagProps } from "@opal/components";
import { Fold } from "@opal/components/fold/components";
import { SvgExpand, SvgFold } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { toPlainString } from "@opal/components/text/InlineMarkdown";

interface CollapsibleProps {
  title: string | RichStr;
  description?: string | RichStr;
  /** Tag shown next to the title. */
  tag?: TagProps;
  /** Controlled open state. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Initial open state when uncontrolled. */
  defaultOpen?: boolean;
  /** Locks the current open state: clicks and keys do not toggle. */
  disabled?: boolean;
  children?: React.ReactNode;
}

function Collapsible({
  title,
  description,
  tag,
  open: openProp,
  onOpenChange,
  defaultOpen = true,
  disabled = false,
  children,
}: CollapsibleProps) {
  const strings = useOpalStrings();
  const [uncontrolledOpen, setUncontrolledOpen] = useState(defaultOpen);
  const [hovered, setHovered] = useState(false);
  const [focusVisible, setFocusVisible] = useState(false);
  const open = openProp ?? uncontrolledOpen;
  // The body renders from the first open and then stays mounted, so a closed
  // section does no work until it is opened and later closes still animate.
  const [hasOpened, setHasOpened] = useState(open);
  if (open && !hasOpened) setHasOpened(true);
  const bodyId = useId();

  function toggle() {
    if (disabled) return;
    const next = !open;
    if (openProp === undefined) setUncontrolledOpen(next);
    onOpenChange?.(next);
  }

  const label = open ? strings.collapsibleFold : strings.collapsibleExpand;
  const plainTitle = toPlainString(title);
  const accessibleLabel = open
    ? strings.collapsibleFoldSection(plainTitle)
    : strings.collapsibleExpandSection(plainTitle);

  return (
    <div
      className="opal-collapsible"
      data-state={open ? "open" : "closed"}
      data-disabled={disabled || undefined}
    >
      {/* Pointer convenience only: the whole row toggles. The Button is the
          keyboard control, and its click (Enter or Space) bubbles up here. */}
      <div
        role="presentation"
        className="opal-collapsible-header"
        onClick={toggle}
        onPointerEnter={() => setHovered(true)}
        onPointerLeave={() => setHovered(false)}
      >
        <ContentAction
          title={title}
          description={description}
          tag={tag}
          sizePreset="main-content"
          variant="section"
          padding={0}
          center
          rightChildren={
            <Button
              icon={open ? SvgFold : SvgExpand}
              prominence="tertiary"
              interaction={
                !disabled && (hovered || focusVisible) ? "hover" : "rest"
              }
              disabled={disabled}
              tooltip={label}
              aria-label={accessibleLabel}
              aria-expanded={open}
              aria-controls={bodyId}
              onFocus={(e) =>
                setFocusVisible(e.currentTarget.matches(":focus-visible"))
              }
              onBlur={() => setFocusVisible(false)}
            />
          }
        />
      </div>
      <Fold open={open} keepMounted id={bodyId}>
        <div className="opal-collapsible-body-content">
          {hasOpened && children}
        </div>
      </Fold>
    </div>
  );
}

export { Collapsible, type CollapsibleProps };
