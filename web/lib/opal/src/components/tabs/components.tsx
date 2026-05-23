"use client";

import "@opal/components/tabs/styles.css";
import React, { useRef, useState, useEffect, useMemo } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { mergeRefs, cn } from "@opal/utils";
import { type IconProps, type WithoutStyles } from "@opal/types";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import { Tooltip, Text, Button } from "@opal/components";
import {
  TabsContext,
  useTabsContext,
  usePillIndicator,
  useHorizontalScroll,
} from "@opal/components/tabs/hooks";

/* =============================================================================
   TABS ROOT
   ============================================================================= */

/**
 * Tabs Root — container for tab navigation and content.
 * Supports both controlled (`value` + `onValueChange`) and uncontrolled
 * (`defaultValue`) modes.
 *
 * @example
 * <Tabs defaultValue="tab1">
 *   <Tabs.List variant="pill">
 *     <Tabs.Trigger value="tab1">Overview</Tabs.Trigger>
 *     <Tabs.Trigger value="tab2">Details</Tabs.Trigger>
 *   </Tabs.List>
 *   <Tabs.Content value="tab1">Overview content</Tabs.Content>
 *   <Tabs.Content value="tab2">Details content</Tabs.Content>
 * </Tabs>
 */
type TabsRootProps = WithoutStyles<
  React.ComponentProps<typeof TabsPrimitive.Root>
>;
function TabsRoot({ ref, ...props }: TabsRootProps) {
  return <TabsPrimitive.Root ref={ref} className="w-full" {...props} />;
}

/* =============================================================================
   TABS LIST
   ============================================================================= */

interface TabsListProps extends WithoutStyles<
  React.ComponentProps<typeof TabsPrimitive.List>
> {
  /**
   * Visual variant of the tab list.
   *
   * - `contained` (default): equal-width grid tabs on a tinted background.
   * - `pill`: content-width tabs with a sliding underline indicator.
   * - `underline`: like pill but without the filled active state.
   */
  variant?: "contained" | "pill" | "underline";
  /** Content pinned to the right of the list. Only visible on pill/underline. */
  rightContent?: React.ReactNode;
  /** Show scroll arrows when tabs overflow (pill/underline only). @default false */
  enableScrollArrows?: boolean;
}

function TabsList({
  ref,
  variant = "contained",
  rightContent,
  enableScrollArrows = false,
  children,
  ...props
}: TabsListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const tabsContainerRef = useRef<HTMLDivElement>(null);
  const scrollArrowsRef = useRef<HTMLDivElement>(null);
  const rightContentRef = useRef<HTMLDivElement>(null);
  const [rightOffset, setRightOffset] = useState(0);
  const isPill = variant === "pill" || variant === "underline";

  const { style: indicatorStyle } = usePillIndicator(
    listRef,
    isPill,
    enableScrollArrows ? tabsContainerRef : undefined
  );
  const contextValue = useMemo(() => ({ variant }), [variant]);
  const {
    canScrollLeft,
    canScrollRight,
    scrollLeft: handleScrollLeft,
    scrollRight: handleScrollRight,
  } = useHorizontalScroll(tabsContainerRef, isPill && enableScrollArrows);

  const showScrollArrows =
    isPill && enableScrollArrows && (canScrollLeft || canScrollRight);

  useEffect(() => {
    if (!isPill) {
      setRightOffset(0);
      return;
    }

    const updateWidth = () => {
      let totalWidth = 0;
      if (scrollArrowsRef.current)
        totalWidth += scrollArrowsRef.current.offsetWidth;
      if (rightContentRef.current)
        totalWidth += rightContentRef.current.offsetWidth;
      setRightOffset(totalWidth);
    };

    updateWidth();

    const resizeObserver = new ResizeObserver(updateWidth);
    if (scrollArrowsRef.current)
      resizeObserver.observe(scrollArrowsRef.current);
    if (rightContentRef.current)
      resizeObserver.observe(rightContentRef.current);

    return () => resizeObserver.disconnect();
  }, [isPill, rightContent, showScrollArrows]);

  return (
    <TabsPrimitive.List
      ref={mergeRefs(listRef, ref)}
      data-variant={variant}
      className="opal-tabs-list"
      style={
        variant === "contained"
          ? {
              gridTemplateColumns: `repeat(${React.Children.count(children)}, 1fr)`,
            }
          : undefined
      }
      {...props}
    >
      <TabsContext.Provider value={contextValue}>
        {isPill ? (
          enableScrollArrows ? (
            <div
              ref={tabsContainerRef}
              className="flex items-center gap-2 overflow-x-auto flex-1 min-w-0"
              style={{ scrollbarWidth: "none", msOverflowStyle: "none" }}
            >
              {children}
            </div>
          ) : (
            <div className="flex items-center gap-2 pt-1">{children}</div>
          )
        ) : (
          children
        )}

        {showScrollArrows && (
          <div
            ref={scrollArrowsRef}
            className="flex items-center gap-1 pl-2 shrink-0"
          >
            <Button
              disabled={!canScrollLeft}
              prominence="tertiary"
              size="sm"
              icon={SvgChevronLeft}
              onClick={handleScrollLeft}
              tooltip="Scroll tabs left"
            />
            <Button
              disabled={!canScrollRight}
              prominence="tertiary"
              size="sm"
              icon={SvgChevronRight}
              onClick={handleScrollRight}
              tooltip="Scroll tabs right"
            />
          </div>
        )}

        {isPill && rightContent && (
          <div ref={rightContentRef} className="ml-auto shrink-0">
            {rightContent}
          </div>
        )}

        {isPill && (
          <>
            {variant !== "underline" && (
              <div
                className="opal-tabs-pill-baseline"
                style={{ right: rightOffset }}
              />
            )}
            <div
              className="opal-tabs-pill-indicator"
              style={{
                left: indicatorStyle.left,
                width: indicatorStyle.width,
                opacity: indicatorStyle.opacity,
              }}
            />
          </>
        )}
      </TabsContext.Provider>
    </TabsPrimitive.List>
  );
}

/* =============================================================================
   TABS TRIGGER
   ============================================================================= */

interface TabsTriggerProps extends WithoutStyles<
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
> {
  ref?: React.Ref<React.ElementRef<typeof TabsPrimitive.Trigger>>;
  /** Tooltip shown on hover. */
  tooltip?: string;
  /** Side where the tooltip appears. @default "top" */
  tooltipSide?: "top" | "bottom" | "left" | "right";
  /** Icon rendered before the label. */
  icon?: React.FunctionComponent<IconProps>;
  /** Show a loading spinner after the label. */
  isLoading?: boolean;
}

function TabsTrigger({
  ref,
  tooltip,
  tooltipSide = "top",
  icon: Icon,
  children,
  disabled,
  isLoading,
  ...props
}: TabsTriggerProps) {
  const context = useTabsContext();
  const variant = context?.variant ?? "contained";

  const inner = (
    <>
      {Icon && (
        <div className="p-0.5">
          <Icon size={14} className="opal-tabs-trigger-icon" />
        </div>
      )}
      {typeof children === "string" ? (
        <div className="px-0.5">
          <Text color="inherit">{children}</Text>
        </div>
      ) : (
        children
      )}
      {isLoading && (
        <span
          className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin ml-1"
          aria-label="Loading"
        />
      )}
    </>
  );

  const trigger = (
    <TabsPrimitive.Trigger
      ref={ref}
      disabled={disabled}
      data-variant={variant}
      className="opal-tabs-trigger"
      {...props}
    >
      {tooltip && !disabled ? (
        <Tooltip tooltip={tooltip} side={tooltipSide}>
          <span className="inline-flex items-center gap-inherit">{inner}</span>
        </Tooltip>
      ) : (
        inner
      )}
    </TabsPrimitive.Trigger>
  );

  // Disabled buttons don't emit pointer events so tooltips won't fire.
  // Wrap only when disabled to preserve layout for the enabled case.
  if (tooltip && disabled) {
    return (
      <Tooltip tooltip={tooltip} side={tooltipSide}>
        <span className="flex-1 inline-flex align-middle justify-center">
          {trigger}
        </span>
      </Tooltip>
    );
  }

  return trigger;
}

/* =============================================================================
   TABS CONTENT
   ============================================================================= */

interface TabsContentProps {
  ref?: React.Ref<React.ElementRef<typeof TabsPrimitive.Content>>;
  value: string;
  /** Padding applied to the content area in rem units. @default 0 */
  padding?: number;
  children?: React.ReactNode;
  className?: string;
}

function TabsContent({
  ref,
  children,
  value,
  className,
  padding = 0,
}: TabsContentProps) {
  return (
    <TabsPrimitive.Content
      ref={ref}
      value={value}
      className={cn(
        "pt-4 focus:outline-hidden focus:border-theme-primary-05 w-full",
        className
      )}
    >
      <div style={{ padding: `${padding}rem` }}>{children}</div>
    </TabsPrimitive.Content>
  );
}

/* =============================================================================
   EXPORTS
   ============================================================================= */

const Tabs = Object.assign(TabsRoot, {
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
});

export {
  Tabs,
  type TabsRootProps,
  type TabsListProps,
  type TabsTriggerProps,
  type TabsContentProps,
};
