"use client";

import "@opal/components/divider/styles.css";
import { useState, useCallback } from "react";
import type { PaddingVariants, RichStr } from "@opal/types";
import { Button, Text } from "@opal/components";
import { SvgChevronRight } from "@opal/icons";
import { Interactive } from "@opal/core";
import { cn } from "@opal/utils";
import { paddingXVariants, paddingYVariants } from "@opal/shared";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DividerSharedProps {
  ref?: React.Ref<HTMLDivElement>;
  title?: never;
  description?: never;
  foldable?: false;
  orientation?: never;
  paddingParallel?: never;
  paddingPerpendicular?: never;
  open?: never;
  defaultOpen?: never;
  onOpenChange?: never;
  children?: never;
}

/** Plain line — no title, no description. */
type DividerBareProps = Omit<
  DividerSharedProps,
  "orientation" | "paddingParallel" | "paddingPerpendicular"
> & {
  /** Orientation of the line. Default: `"horizontal"`. */
  orientation?: "horizontal" | "vertical";
  /** Padding along the line direction. Default: `"sm"` (0.5rem). */
  paddingParallel?: PaddingVariants;
  /** Padding perpendicular to the line. Default: `"xs"` (0.25rem). */
  paddingPerpendicular?: PaddingVariants;
};

/** Line with a title to the left. */
type DividerTitledProps = Omit<DividerSharedProps, "title"> & {
  title: string | RichStr;
};

/** Line with a description below. */
type DividerDescribedProps = Omit<DividerSharedProps, "description"> & {
  /** Description rendered below the divider line. */
  description: string | RichStr;
};

/** Foldable — requires title, reveals children. */
type DividerFoldableProps = Omit<
  DividerSharedProps,
  "title" | "foldable" | "open" | "defaultOpen" | "onOpenChange" | "children"
> & {
  /** Title is required when foldable. */
  title: string | RichStr;
  foldable: true;
  /** Controlled open state. */
  open?: boolean;
  /** Uncontrolled default open state. */
  defaultOpen?: boolean;
  /** Callback when open state changes. */
  onOpenChange?: (open: boolean) => void;
  /** Content revealed when open. */
  children?: React.ReactNode;
};

type DividerProps =
  | DividerBareProps
  | DividerTitledProps
  | DividerDescribedProps
  | DividerFoldableProps;

// ---------------------------------------------------------------------------
// Divider
// ---------------------------------------------------------------------------

function Divider(props: DividerProps) {
  if (props.foldable) {
    return <FoldableDivider {...props} />;
  }

  const {
    ref,
    title,
    description,
    orientation = "horizontal",
    paddingParallel = "sm",
    paddingPerpendicular = "xs",
  } = props;

  if (orientation === "vertical") {
    return (
      <div
        ref={ref}
        className={cn(
          "opal-divider-vertical",
          paddingXVariants[paddingPerpendicular],
          paddingYVariants[paddingParallel]
        )}
      >
        <div className="opal-divider-line-vertical" />
      </div>
    );
  }

  return (
    <div
      ref={ref}
      className={cn(
        "opal-divider",
        paddingXVariants[paddingParallel],
        paddingYVariants[paddingPerpendicular]
      )}
    >
      <div className="opal-divider-row">
        {title && (
          <div className="opal-divider-title">
            <Text font="secondary-body" color="text-03" nowrap>
              {title}
            </Text>
          </div>
        )}
        <div className="opal-divider-line" />
      </div>
      {description && (
        <div className="opal-divider-description">
          <Text font="secondary-body" color="text-03">
            {description}
          </Text>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// FoldableDivider (internal)
// ---------------------------------------------------------------------------

function FoldableDivider({
  title,
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  children,
}: DividerFoldableProps) {
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : internalOpen;

  const toggle = useCallback(() => {
    const next = !isOpen;
    if (!isControlled) setInternalOpen(next);
    onOpenChange?.(next);
  }, [isOpen, isControlled, onOpenChange]);

  return (
    <>
      <Interactive.Stateless
        variant="default"
        prominence="tertiary"
        interaction={isOpen ? "hover" : "rest"}
        onClick={toggle}
      >
        <Interactive.Container
          roundingVariant="sm"
          heightVariant="fit"
          widthVariant="full"
        >
          <div className="opal-divider">
            <div className="opal-divider-row">
              <div className="opal-divider-title">
                <Text font="secondary-body" color="inherit" nowrap>
                  {title}
                </Text>
              </div>
              <div className="opal-divider-line" />
              <div className="opal-divider-chevron" data-open={isOpen}>
                <Button
                  icon={SvgChevronRight}
                  size="sm"
                  prominence="tertiary"
                />
              </div>
            </div>
          </div>
        </Interactive.Container>
      </Interactive.Stateless>
      {isOpen && children}
    </>
  );
}

export { Divider, type DividerProps };
