"use client";

import "@opal/components/divider/styles.css";
import { useState, useCallback } from "react";
import type { OrientationVariants, RichStr } from "@opal/types";
import { Button, Text } from "@opal/components";
import { SvgChevronRight } from "@opal/icons";
import { Interactive, type InteractiveStatelessInteraction } from "@opal/core";
import { cn } from "@opal/utils";
import { spacingToRem } from "@opal/shared";

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
  interaction?: never;
}

/**
 * The insets a divider offers, as spacing steps (`N / 4` rem).
 *
 * A closed set rather than an open number: a divider's inset is a shared rhythm
 * across the surfaces it separates, so an arbitrary step would only ever put one
 * divider out of step with the rest.
 */
type DividerSpacing = 0 | 0.5 | 1 | 2 | 3 | 4 | 6;

/** Plain line — no title, no description. */
type DividerBareProps = Omit<
  DividerSharedProps,
  "orientation" | "paddingParallel" | "paddingPerpendicular"
> & {
  /** Orientation of the line. Default: `"horizontal"`. */
  orientation?: OrientationVariants;
  /** Padding along the line direction, as a spacing step. Default: 0.375rem. */
  paddingParallel?: DividerSpacing;
  /** Padding perpendicular to the line, as a spacing step. Default: 0.25rem. */
  paddingPerpendicular?: DividerSpacing;
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
  | "title"
  | "foldable"
  | "open"
  | "defaultOpen"
  | "onOpenChange"
  | "children"
  | "interaction"
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
  /**
   * Content revealed when open. Stays mounted while closed, inert and
   * hidden from assistive tech, so the fold animates both ways.
   */
  children?: React.ReactNode;
  /**
   * Overrides the header's interaction state (a listbox highlights the
   * title the keyboard stopped on). Unset, an open header reads as hover.
   */
  interaction?: InteractiveStatelessInteraction;
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
    paddingParallel,
    paddingPerpendicular,
  } = props;

  // The stylesheet carries the default inset (0.375rem along the line, 0.25rem
  // across, the same for every variant); a bare line's steps override it.
  const inset = {
    ...(paddingParallel !== undefined && {
      parallel: spacingToRem(paddingParallel),
    }),
    ...(paddingPerpendicular !== undefined && {
      perpendicular: spacingToRem(paddingPerpendicular),
    }),
  };

  if (orientation === "vertical") {
    return (
      <div
        ref={ref}
        className="opal-divider-vertical"
        style={{
          paddingInline: inset.perpendicular,
          paddingBlock: inset.parallel,
        }}
      >
        <div className="opal-divider-line-vertical" />
      </div>
    );
  }

  return (
    <div
      ref={ref}
      className="opal-divider"
      style={{
        paddingInline: inset.parallel,
        paddingBlock: inset.perpendicular,
      }}
    >
      <div className="opal-divider-row">
        {title && (
          <div className="opal-divider-title">
            <Text
              font="secondary-body"
              color="text-03"
              wordWrap="whitespace-nowrap"
            >
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
  interaction,
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
        interaction={interaction ?? (isOpen ? "hover" : "rest")}
        onClick={toggle}
      >
        <Interactive.Container rounding={2} size="fit" width="full">
          <div className="opal-divider">
            <div className="opal-divider-row">
              <div className="opal-divider-title">
                <Text
                  font="secondary-body"
                  color="inherit"
                  wordWrap="whitespace-nowrap"
                >
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
      {/* The content stays mounted so the fold can close as smoothly as it
          opens; closed, it is inert and hidden from assistive tech. */}
      <div
        className="opal-divider-fold"
        data-open={isOpen}
        aria-hidden={!isOpen || undefined}
        inert={!isOpen || undefined}
      >
        <div className="opal-divider-fold-inner">{children}</div>
      </div>
    </>
  );
}

export { Divider, type DividerProps, type DividerSpacing };
