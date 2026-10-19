"use client";

import "@opal/components/tabs/styles.css";
import React, { useRef, useState, useEffect, useMemo } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn, mergeRefs } from "@opal/utils";
import {
  IconFunctionComponent,
  type RichStr,
  type Spacing,
  type WithoutStyles,
} from "@opal/types";
import { spacingToRem } from "@opal/shared";
// The scroll arrows are physical controls, so they use the raw chevrons
// instead of the barrel's RTL-mirrored wrappers.
import SvgChevronLeft from "@opal/icons/chevron-left";
import SvgChevronRight from "@opal/icons/chevron-right";
import { Tooltip, Button, type TooltipSide } from "@opal/components";
import { Content } from "@opal/layouts";
import { Interactive } from "@opal/core";
import { IconLoader } from "@opal/loaders/icon-loader/components";
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

  /**
   * Space between the tab list and the panel below it, as a {@link Spacing}
   * step (`N / 4` rem). Unset, the panel sits flush against the list.
   */
  gap?: Spacing;
}

function TabsRoot({
  variant = "contained",
  gap,
  value,
  defaultValue,
  onValueChange,
  activationMode = "manual",
  ...props
}: TabsRootProps) {
  // Tracked here as well as in Radix, so each trigger knows whether it is
  // the selected one.
  const [uncontrolledValue, setUncontrolledValue] = useState(defaultValue);
  const activeValue = value ?? uncontrolledValue;
  const contextValue = useMemo(
    () => ({ variant, activeValue }),
    [variant, activeValue]
  );
  return (
    <TabsContext.Provider value={contextValue}>
      <TabsPrimitive.Root
        {...props}
        // Arrows only move focus, which paints the hover state; Enter or
        // Space selects.
        activationMode={activationMode}
        value={activeValue}
        onValueChange={(next) => {
          if (value === undefined) setUncontrolledValue(next);
          onValueChange?.(next);
        }}
        className={cn("w-full", gap !== undefined && "flex flex-col")}
        style={gap !== undefined ? { gap: spacingToRem(gap) } : undefined}
      />
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

/** Keys that move focus between tabs. */
const FOCUS_KEYS = new Set(["ArrowLeft", "ArrowRight", "Home", "End", "Tab"]);

function TabsList({
  ref,
  rightChildren,
  enableScrollArrows = false,
  children,
  ...props
}: TabsListProps) {
  const listRef = useRef<HTMLDivElement>(null);
  // The row of tabs. On pill/underline the surface and indicator live in it,
  // so they scroll, clip and overscroll with the tabs.
  const rowRef = useRef<HTMLDivElement>(null);
  const scrollArrowsRef = useRef<HTMLDivElement>(null);
  const rightChildrenRef = useRef<HTMLDivElement>(null);
  const [rightOffset, setRightOffset] = useState(0);
  // The focus ring shows from an arrow or the Tab key until a click, Escape, or
  // focus leaving the list. The browser's `:focus-visible` cannot follow
  // this: after a click it keeps the ring hidden for the arrows too.
  const [keyboardFocus, setKeyboardFocus] = useState(false);
  // Radix moves focus after the key, so the ring waits for that focus and
  // appears on the next tab, not first on this one.
  const keyMovedFocusRef = useRef(false);
  const strings = useOpalStrings();
  const { variant } = useTabsContext() ?? { variant: "contained" as const };
  const isPill = variant === "pill" || variant === "underline";

  const { style: indicatorStyle, measured } = useTabIndicator(
    listRef,
    isPill ? rowRef : listRef
  );
  // The indicators slide between tabs, but not on their first placement.
  const indicatorState = { "data-measured": measured || undefined };
  const {
    canScrollLeft,
    canScrollRight,
    scrollLeft: handleScrollLeft,
    scrollRight: handleScrollRight,
  } = useHorizontalScroll(rowRef, isPill && enableScrollArrows);

  // Centred in the 2.25rem underline bar; pill keeps its smaller arrows.
  const arrowSize = variant === "underline" ? "md" : "sm";

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

  // The active tab's surface. It slides from tab to tab behind the triggers,
  // which only change their text colour. Underline has none.
  const surface = variant !== "underline" && (
    <div
      className="opal-tabs-surface"
      data-variant={variant}
      {...indicatorState}
      style={{
        // A transform, not left/top: the browser composites it on the GPU
        // and moves it by sub-pixels, so the slide does not stutter.
        transform: `translate(${indicatorStyle.left}px, ${indicatorStyle.top}px)`,
        width: indicatorStyle.width,
        height: indicatorStyle.height,
        opacity: indicatorStyle.opacity,
      }}
    />
  );

  return (
    <TabsPrimitive.List
      ref={mergeRefs(listRef, ref)}
      data-variant={variant}
      data-focus-ring={keyboardFocus || undefined}
      className="opal-tabs-list"
      // Each tab is its own Tab stop (see Tabs.Trigger), so the list is not
      // one. Radix would otherwise make it the entry point.
      tabIndex={-1}
      style={
        variant === "contained"
          ? {
              gridTemplateColumns: `repeat(${React.Children.toArray(children).length}, 1fr)`,
            }
          : undefined
      }
      {...props}
      onKeyDown={(event) => {
        props.onKeyDown?.(event);
        if (event.key === "Escape") {
          // Escape leaves the tabs: the tab loses focus, and its ring.
          keyMovedFocusRef.current = false;
          setKeyboardFocus(false);
          if (event.target instanceof HTMLElement) event.target.blur();
        } else if (FOCUS_KEYS.has(event.key)) {
          keyMovedFocusRef.current = true;
        }
      }}
      onMouseDown={(event) => {
        props.onMouseDown?.(event);
        keyMovedFocusRef.current = false;
        setKeyboardFocus(false);
      }}
      onFocus={(event) => {
        props.onFocus?.(event);
        const fromKey = keyMovedFocusRef.current;
        keyMovedFocusRef.current = false;
        // A key in the list moved focus, or Tab came in from outside it (the
        // browser marks that as keyboard focus).
        if (
          fromKey ||
          (!event.currentTarget.contains(event.relatedTarget) &&
            event.target.matches(":focus-visible"))
        ) {
          setKeyboardFocus(true);
        }
      }}
      onBlur={(event) => {
        props.onBlur?.(event);
        if (!event.currentTarget.contains(event.relatedTarget)) {
          setKeyboardFocus(false);
        }
      }}
    >
      {isPill ? (
        <div
          ref={rowRef}
          className={cn(
            "opal-tabs-row",
            enableScrollArrows
              ? "overflow-x-auto flex-1 min-w-0"
              : variant === "pill" && "pt-1"
          )}
          style={
            enableScrollArrows
              ? { scrollbarWidth: "none", msOverflowStyle: "none" }
              : undefined
          }
        >
          {surface}
          {children}
          <div
            className="opal-tabs-pill-indicator"
            {...indicatorState}
            style={{
              transform: `translateX(${indicatorStyle.left}px)`,
              width: indicatorStyle.width,
              opacity: indicatorStyle.opacity,
            }}
          />
        </div>
      ) : (
        <>
          {surface}
          {children}
        </>
      )}

      {showScrollArrows && (
        <div
          ref={scrollArrowsRef}
          className="flex items-center gap-1 ps-2 shrink-0"
        >
          <Button
            disabled={!canScrollLeft}
            prominence="tertiary"
            size={arrowSize}
            icon={SvgChevronLeft}
            onClick={handleScrollLeft}
            tooltip={strings.scrollTabsLeft}
          />
          <Button
            disabled={!canScrollRight}
            prominence="tertiary"
            size={arrowSize}
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

      {variant === "pill" && (
        <div
          className="opal-tabs-pill-baseline"
          style={{ insetInlineEnd: rightOffset }}
        />
      )}
    </TabsPrimitive.List>
  );
}

/* =============================================================================
   TABS TRIGGER
   ============================================================================= */

interface TabsTriggerProps extends WithoutStyles<
  Omit<React.ComponentProps<typeof TabsPrimitive.Trigger>, "children">
> {
  /** The tab's label. */
  children: string | RichStr;
  /** Smaller text below the label. Contained tabs only; other variants ignore it. */
  description?: string | RichStr;
  /** Tooltip shown on hover. */
  tooltip?: string;
  /** Side where the tooltip appears. @default "top" */
  tooltipSide?: TooltipSide;
  /** Icon rendered before the label. */
  icon?: IconFunctionComponent;
  /** Show a loading spinner after the label. */
  isLoading?: boolean;
}

function TabsTrigger({
  tooltip,
  tooltipSide = "top",
  icon,
  isLoading,
  description,

  ref,
  children,
  disabled,
  ...props
}: TabsTriggerProps) {
  const { variant, activeValue } = useTabsContext() ?? {
    variant: "contained" as const,
    activeValue: undefined,
  };
  const isActive = props.value === activeValue;
  const sizePreset = variant === "contained" ? "main-ui" : "secondary";
  // Only contained tabs have room for a description.
  const shownDescription = variant === "contained" ? description : undefined;

  useEffect(() => {
    if (
      process.env.NODE_ENV !== "production" &&
      description !== undefined &&
      variant !== "contained"
    ) {
      console.warn(
        `Tabs.Trigger: description is only shown on contained tabs, not "${variant}".`
      );
    }
  }, [description, variant]);

  // The label is always a Content, which takes its title and icon colours
  // from this trigger's interactive foregrounds (set per state in styles.css)
  // and its font from the variant's size. Fit, so the trigger's
  // justify-center centres it.
  const inner = (
    <>
      {shownDescription === undefined ? (
        <Content
          icon={icon}
          title={children}
          color="interactive"
          sizePreset={sizePreset}
          variant="body"
          width="fit"
        />
      ) : (
        <Content
          icon={icon}
          title={children}
          description={shownDescription}
          color="interactive"
          sizePreset={sizePreset}
          variant="section"
          width="fit"
        />
      )}
      {isLoading && (
        // Sized and spaced like the label's own icon: 1rem on contained
        // (main-ui), 0.75rem otherwise (secondary), 0.25rem from the title.
        <IconLoader
          className={cn(
            "ms-1 interactive-foreground-icon",
            variant === "contained" ? "size-4" : "size-3"
          )}
        />
      )}
    </>
  );

  // An Interactive surface: hover, pressed and disabled text colours come
  // from the default tertiary styles (styles.css drops their backgrounds).
  // The selected tab holds the hover state.
  const trigger = (
    <Interactive.Stateless
      variant="default"
      prominence="tertiary"
      type="button"
      disabled={disabled}
      interaction={isActive ? "hover" : "rest"}
    >
      <TabsPrimitive.Trigger
        ref={ref}
        disabled={disabled}
        data-variant={variant}
        className="opal-tabs-trigger"
        // Tab steps through every tab, as well as the arrows.
        tabIndex={0}
        {...props}
        onMouseDown={(event) => {
          props.onMouseDown?.(event);
          // Safari and Firefox on macOS do not focus a clicked button, and
          // the arrows move from the focused tab. Only a plain left click,
          // as Radix selects on: focus selects in automatic mode.
          if (
            !disabled &&
            !event.defaultPrevented &&
            event.button === 0 &&
            !event.ctrlKey
          ) {
            event.currentTarget.focus();
          }
        }}
      >
        {tooltip && !disabled ? (
          <Tooltip tooltip={tooltip} side={tooltipSide}>
            <span className="inline-flex items-center gap-inherit">
              {inner}
            </span>
          </Tooltip>
        ) : (
          inner
        )}
      </TabsPrimitive.Trigger>
    </Interactive.Stateless>
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
