"use client";

import "@opal/components/tabs/styles.css";
import React, { useRef, useState, useEffect, useMemo } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn, mergeRefs } from "@opal/utils";
import {
  IconFunctionComponent,
  type Spacing,
  type WithoutStyles,
} from "@opal/types";
import { spacingToRem } from "@opal/shared";
// The scroll arrows are physical controls, so they use the raw chevrons
// instead of the barrel's RTL-mirrored wrappers.
import SvgChevronLeft from "@opal/icons/chevron-left";
import SvgChevronRight from "@opal/icons/chevron-right";
import { Tooltip, Button } from "@opal/components";
import { Content } from "@opal/layouts";
import {
  TabsContext,
  useTabsContext,
  useTabIndicator,
  useHorizontalScroll,
} from "@opal/components/tabs/hooks";
import { useOpalStrings } from "@opal/strings";

/* =============================================================================
   TABS ROOT
   ============================================================================= */

interface TabsRootProps extends WithoutStyles<
  React.ComponentProps<typeof TabsPrimitive.Root>
> {
  /**
   * Visual variant applied to the whole tab group.
   *
   * - `contained` (default): equal-width grid tabs on a tinted background.
   * - `pill`: content-width tabs with a sliding underline indicator.
   * - `underline`: like pill but without the filled active state.
   */
  variant?: "contained" | "pill" | "underline";
}

function TabsRoot({ variant = "contained", ...props }: TabsRootProps) {
  const contextValue = useMemo(() => ({ variant }), [variant]);
  return (
    <TabsContext.Provider value={contextValue}>
      <TabsPrimitive.Root className="w-full" {...props} />
    </TabsContext.Provider>
  );
}

/* =============================================================================
   TABS LIST
   ============================================================================= */

interface TabsListProps extends WithoutStyles<
  React.ComponentProps<typeof TabsPrimitive.List>
> {
  /** Content pinned to the right of the list. Only visible on pill/underline. */
  rightChildren?: React.ReactNode;
  /** Show scroll arrows when tabs overflow (pill/underline only). @default false */
  enableScrollArrows?: boolean;
}

function TabsList({
  ref,
  rightChildren,
  enableScrollArrows = false,
  children,
  ...props
}: TabsListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  const tabsContainerRef = useRef<HTMLDivElement>(null);
  const scrollArrowsRef = useRef<HTMLDivElement>(null);
  const rightChildrenRef = useRef<HTMLDivElement>(null);
  const [rightOffset, setRightOffset] = useState(0);
  const strings = useOpalStrings();
  const { variant } = useTabsContext() ?? { variant: "contained" as const };
  const isPill = variant === "pill" || variant === "underline";

  const {
    style: indicatorStyle,
    isScrolling,
    measured,
  } = useTabIndicator(
    listRef,
    true,
    enableScrollArrows ? tabsContainerRef : undefined
  );
  // The indicators slide between tabs, but not on their first placement and
  // not while the tabs scroll under them.
  const indicatorState = {
    "data-measured": measured || undefined,
    "data-scrolling": isScrolling || undefined,
  };
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
      if (rightChildrenRef.current)
        totalWidth += rightChildrenRef.current.offsetWidth;
      setRightOffset(totalWidth);
    };

    updateWidth();

    const resizeObserver = new ResizeObserver(updateWidth);
    if (scrollArrowsRef.current)
      resizeObserver.observe(scrollArrowsRef.current);
    if (rightChildrenRef.current)
      resizeObserver.observe(rightChildrenRef.current);

    return () => resizeObserver.disconnect();
  }, [isPill, rightChildren, showScrollArrows]);

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
      {/* The active tab's surface. It slides from tab to tab behind the
          triggers, which only change their text colour. Underline has none. */}
      {variant !== "underline" && (
        <div
          className="opal-tabs-surface"
          data-variant={variant}
          {...indicatorState}
          style={{
            // A transform, not left/top: the browser composites it on the
            // GPU and moves it by sub-pixels, so the slide does not stutter.
            transform: `translate(${indicatorStyle.left}px, ${indicatorStyle.top}px)`,
            width: indicatorStyle.width,
            height: indicatorStyle.height,
            opacity: indicatorStyle.opacity,
          }}
        />
      )}

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
          className="flex items-center gap-1 ps-2 shrink-0"
        >
          <Button
            disabled={!canScrollLeft}
            prominence="tertiary"
            size="sm"
            icon={SvgChevronLeft}
            onClick={handleScrollLeft}
            tooltip={strings.scrollTabsLeft}
          />
          <Button
            disabled={!canScrollRight}
            prominence="tertiary"
            size="sm"
            icon={SvgChevronRight}
            onClick={handleScrollRight}
            tooltip={strings.scrollTabsRight}
          />
        </div>
      )}

      {isPill && rightChildren && (
        <div ref={rightChildrenRef} className="ms-auto shrink-0">
          {rightChildren}
        </div>
      )}

      {isPill && (
        <>
          {variant !== "underline" && (
            <div
              className="opal-tabs-pill-baseline"
              style={{ insetInlineEnd: rightOffset }}
            />
          )}
          <div
            className="opal-tabs-pill-indicator"
            {...indicatorState}
            style={{
              transform: `translateX(${indicatorStyle.left}px)`,
              width: indicatorStyle.width,
              opacity: indicatorStyle.opacity,
            }}
          />
        </>
      )}
    </TabsPrimitive.List>
  );
}

/* =============================================================================
   TABS TRIGGER
   ============================================================================= */

interface TabsTriggerProps extends WithoutStyles<
  React.ComponentProps<typeof TabsPrimitive.Trigger>
> {
  /** Tooltip shown on hover. */
  tooltip?: string;
  /** Side where the tooltip appears. @default "top" */
  tooltipSide?: "top" | "bottom" | "left" | "right";
  /** Icon rendered before the label. */
  icon?: IconFunctionComponent;
  /** Show a loading spinner after the label. */
  isLoading?: boolean;
}

function TabsTrigger({
  tooltip,
  tooltipSide = "top",
  icon: Icon,
  isLoading,

  ref,
  children,
  disabled,
  ...props
}: TabsTriggerProps) {
  const { variant } = useTabsContext() ?? { variant: "contained" as const };
  const strings = useOpalStrings();

  // A string label renders as Content, which takes its title and icon
  // colours from this trigger's interactive foregrounds (set per state in
  // styles.css) and its font from the variant's size.
  const inner = (
    <>
      {typeof children === "string" ? (
        <Content
          icon={Icon}
          title={children}
          color="interactive"
          sizePreset={variant === "contained" ? "main-ui" : "secondary"}
          variant="body"
          // Fit, so the trigger's justify-center centres the label.
          width="fit"
        />
      ) : (
        <>
          {Icon && (
            <div className="p-0.5">
              <Icon size={14} className="interactive-foreground-icon" />
            </div>
          )}
          {children}
        </>
      )}
      {isLoading && (
        <span
          className="inline-block w-3 h-3 border-2 border-current border-t-transparent rounded-full animate-spin ms-1"
          aria-label={strings.loading}
        />
      )}
    </>
  );

  const trigger = (
    <TabsPrimitive.Trigger
      ref={ref}
      disabled={disabled}
      data-variant={variant}
      // An interactive surface, so a Content inside follows its foregrounds.
      className="interactive opal-tabs-trigger"
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
interface TabsContentProps extends WithoutStyles<
  React.ComponentProps<typeof TabsPrimitive.Content>
> {
  /** Additional inner padding, as a {@link Spacing} step (`N / 4` rem). @default 0 */
  padding?: Spacing;
  /** Keep the panel mounted while inactive, hidden, so its state survives a tab switch. @default false */
  keepMounted?: boolean;
}

function TabsContent({
  padding,
  keepMounted = false,
  children,
  ...props
}: TabsContentProps) {
  return (
    <TabsPrimitive.Content
      {...props}
      forceMount={keepMounted || undefined}
      className={cn("w-full", keepMounted && "data-[state=inactive]:hidden")}
    >
      {padding ? (
        <div style={{ padding: spacingToRem(padding) }}>{children}</div>
      ) : (
        children
      )}
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

export { Tabs, type TabsRootProps, type TabsListProps, type TabsTriggerProps };
