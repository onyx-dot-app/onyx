"use client";

import "@opal/components/divider/styles.css";
import { useState, useCallback } from "react";
import type { RichStr } from "@opal/types";
import { Button, Text } from "@opal/components";
import { SvgChevronRight } from "@opal/icons";
import { Interactive } from "@opal/core";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DividerNeverFields {
  open?: never;
  defaultOpen?: never;
  onOpenChange?: never;
  children?: never;
}

/** Plain line — no title, no description. */
interface DividerBareProps extends DividerNeverFields {
  title?: never;
  description?: never;
  foldable?: false;
  ref?: React.Ref<HTMLDivElement>;
}

/** Line with a title to the left. */
interface DividerTitledProps extends DividerNeverFields {
  title: string | RichStr;
  description?: never;
  foldable?: false;
  ref?: React.Ref<HTMLDivElement>;
}

/** Line with a description below. */
interface DividerDescribedProps extends DividerNeverFields {
  title?: never;
  /** Description rendered below the divider line. */
  description: string | RichStr;
  foldable?: false;
  ref?: React.Ref<HTMLDivElement>;
}

/** Foldable — requires title, reveals children. */
interface DividerFoldableProps {
  /** Title is required when foldable. */
  title: string | RichStr;
  foldable: true;
  description?: never;
  /** Controlled open state. */
  open?: boolean;
  /** Uncontrolled default open state. */
  defaultOpen?: boolean;
  /** Callback when open state changes. */
  onOpenChange?: (open: boolean) => void;
  /** Content revealed when open. */
  children?: React.ReactNode;
  ref?: React.Ref<HTMLDivElement>;
}

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

  const { ref } = props;
  const title = "title" in props ? props.title : undefined;
  const description = "description" in props ? props.description : undefined;

  return (
    <div ref={ref} className="opal-divider">
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
