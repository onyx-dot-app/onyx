"use client";

import React, { useRef, useState, useEffect, useMemo } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn, mergeRefs } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { WithoutStyles } from "@/types";
import { Section, SectionProps } from "@/layouts/general-layouts";
import { IconProps } from "@opal/types";
import Text from "./texts/Text";

/* =============================================================================
   CONTEXT
   ============================================================================= */

interface TabsContextValue {
  variant: "contained" | "pill";
}

const TabsContext = React.createContext<TabsContextValue | undefined>(
  undefined
);

const useTabsContext = () => {
  const context = React.useContext(TabsContext);
  return context; // Returns undefined if used outside Tabs.List (allows explicit override)
};

/**
 * TABS COMPONENT VARIANTS
 *
 * Contained (default):
 * ┌─────────────────────────────────────────────────┐
 * │ ┌──────────┐ ╔══════════╗ ┌──────────┐         │
 * │ │   Tab 1  │ ║  Tab 2   ║ │   Tab 3  │         │  ← gray background
 * │ └──────────┘ ╚══════════╝ └──────────┘         │
 * └─────────────────────────────────────────────────┘
 *                 ↑ active tab (white bg, shadow)
 *
 * Pill:
 *    Tab 1      Tab 2      Tab 3          [Action]
 *              ╔═════╗
 *              ║     ║                        ↑ optional rightContent
 * ────────────╨═════╨─────────────────────────────
 *              ↑ sliding indicator under active tab
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

/* =============================================================================
   VARIANT STYLES
   Centralized styling definitions for tabs variants.
   ============================================================================= */

/** Style classes for TabsList variants */
const listVariants = {
  contained: "grid w-full rounded-08 bg-background-tint-03",
  pill: "relative flex items-center pb-[4px] bg-background-tint-00",
} as const;

/** Base style classes for TabsTrigger variants */
const triggerBaseStyles = {
  contained: "p-2 gap-2",
  pill: "p-1.5 font-secondary-action transition-all duration-200 ease-out",
} as const;

/** Icon style classes for TabsTrigger variants */
const iconVariants = {
  contained: "stroke-text-03",
  pill: "stroke-current",
} as const;

/* =============================================================================
   HOOKS
   ============================================================================= */

/** Style properties for the pill indicator position */
interface IndicatorStyle {
  left: number;
  width: number;
  opacity: number;
}

/**
 * Hook to track and animate a sliding indicator under the active tab.
 *
 * Uses MutationObserver to detect when the active tab changes (via data-state
 * attribute updates from Radix UI) and calculates the indicator position.
 *
 * @param listRef - Ref to the TabsList container element
 * @param enabled - Whether indicator tracking is enabled (only true for pill variant)
 * @returns Style object with left, width, and opacity for the indicator element
 */
function usePillIndicator(
  listRef: React.RefObject<HTMLElement | null>,
  enabled: boolean
): IndicatorStyle {
  const [style, setStyle] = useState<IndicatorStyle>({
    left: 0,
    width: 0,
    opacity: 0,
  });

  useEffect(() => {
    if (!enabled) return;

    const updateIndicator = () => {
      const list = listRef.current;
      if (!list) return;

      const activeTab = list.querySelector<HTMLElement>(
        '[data-state="active"]'
      );
      if (activeTab) {
        const listRect = list.getBoundingClientRect();
        const tabRect = activeTab.getBoundingClientRect();
        setStyle({
          left: tabRect.left - listRect.left,
          width: tabRect.width,
          opacity: 1,
        });
      }
    };

    updateIndicator();

    const observer = new MutationObserver(updateIndicator);
    if (listRef.current) {
      observer.observe(listRef.current, {
        attributes: true,
        subtree: true,
        attributeFilter: ["data-state"],
      });
    }

    return () => observer.disconnect();
  }, [enabled, listRef]);

  return style;
}

/* =============================================================================
   SUB-COMPONENTS
   ============================================================================= */

/**
 * Renders the bottom line and sliding indicator for the pill variant.
 * The indicator animates smoothly when switching between tabs.
 */
function PillIndicator({ style }: { style: IndicatorStyle }) {
  return (
    <>
      <div className="absolute bottom-0 left-0 right-0 h-px bg-border-02 pointer-events-none" />
      <div
        className="absolute bottom-0 h-[2px] bg-background-tint-inverted-03 z-10 transition-all duration-200 ease-out pointer-events-none"
        style={{
          left: style.left,
          width: style.width,
          opacity: style.opacity,
        }}
      />
    </>
  );
}

/* =============================================================================
   MAIN COMPONENTS
   ============================================================================= */

/**
 * Tabs Root Component
 *
 * Container for tab navigation and content. Manages the active tab state.
 * Supports both controlled and uncontrolled modes.
 *
 * @param defaultValue - The tab value that should be active by default (uncontrolled mode)
 * @param value - The controlled active tab value
 * @param onValueChange - Callback fired when the active tab changes
 */
const TabsRoot = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Root>,
  WithoutStyles<React.ComponentPropsWithoutRef<typeof TabsPrimitive.Root>>
>(({ ...props }, ref) => (
  <TabsPrimitive.Root ref={ref} className="w-full" {...props} />
));
TabsRoot.displayName = TabsPrimitive.Root.displayName;

/* -------------------------------------------------------------------------- */

/**
 * Tabs List Props
 */
interface TabsListProps
  extends WithoutStyles<
    React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
  > {
  /**
   * Visual variant of the tabs list.
   *
   * - `contained` (default): Rounded background with equal-width tabs in a grid.
   *   Best for primary navigation where tabs should fill available space.
   *
   * - `pill`: Transparent background with a sliding underline indicator.
   *   Best for secondary navigation or filter-style tabs with flexible widths.
   */
  variant?: "contained" | "pill";

  /**
   * Content to render on the right side of the tab list.
   * Only applies to the `pill` variant (ignored for `contained`).
   *
   * @example
   * ```tsx
   * <Tabs.List variant="pill" rightContent={<Button size="sm">Add New</Button>}>
   *   <Tabs.Trigger value="all">All</Tabs.Trigger>
   *   <Tabs.Trigger value="active">Active</Tabs.Trigger>
   * </Tabs.List>
   * ```
   */
  rightContent?: React.ReactNode;
}

/**
 * Tabs List Component
 *
 * Container for tab triggers. Renders as a horizontal list with automatic
 * keyboard navigation (arrow keys, Home/End) and accessibility attributes.
 *
 * @remarks
 * - **Contained**: Uses CSS Grid for equal-width tabs with rounded background
 * - **Pill**: Uses Flexbox for content-width tabs with animated bottom indicator
 * - The `variant` prop is automatically propagated to child `Tabs.Trigger` components via context
 */
const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  TabsListProps
>(({ variant = "contained", rightContent, children, ...props }, ref) => {
  const listRef = useRef<HTMLDivElement>(null);
  const isPill = variant === "pill";
  const indicatorStyle = usePillIndicator(listRef, isPill);
  const contextValue = useMemo(() => ({ variant }), [variant]);

  return (
    <TabsPrimitive.List
      ref={mergeRefs(listRef, ref)}
      className={cn(listVariants[variant])}
      style={
        variant === "contained"
          ? {
              gridTemplateColumns: `repeat(${React.Children.count(
                children
              )}, 1fr)`,
            }
          : undefined
      }
      {...props}
    >
      <TabsContext.Provider value={contextValue}>
        {isPill ? (
          <div className="flex items-center gap-2">{children}</div>
        ) : (
          children
        )}

        {isPill && rightContent && (
          <div className="ml-auto pl-2">{rightContent}</div>
        )}

        {isPill && <PillIndicator style={indicatorStyle} />}
      </TabsContext.Provider>
    </TabsPrimitive.List>
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

/* -------------------------------------------------------------------------- */

/**
 * Tabs Trigger Props
 */
interface TabsTriggerProps
  extends WithoutStyles<
    Omit<
      React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>,
      "children"
    >
  > {
  /**
   * Visual variant of the tab trigger.
   * Automatically inherited from the parent `Tabs.List` variant via context.
   * Can be explicitly set to override the inherited value.
   *
   * - `contained` (default): White background with shadow when active
   * - `pill`: Dark pill background when active, transparent when inactive
   */
  variant?: "contained" | "pill";

  /** Optional tooltip text to display on hover */
  tooltip?: string;

  /** Side where tooltip appears. @default "top" */
  tooltipSide?: "top" | "bottom" | "left" | "right";

  /** Optional icon component to render before the label */
  icon?: React.FunctionComponent<IconProps>;

  /** Tab label - can be string or ReactNode for custom content */
  children?: React.ReactNode;

  /** Show loading spinner after label */
  isLoading?: boolean;
}

/**
 * Tabs Trigger Component
 *
 * Individual tab button that switches the active tab when clicked.
 * Supports icons, tooltips, loading states, and disabled state.
 *
 * @remarks
 * - **Contained active**: White background with subtle shadow
 * - **Pill active**: Dark inverted background
 * - Tooltips work on disabled triggers via wrapper span technique
 * - Loading spinner appears after the label text
 */
const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  TabsTriggerProps
>(
  (
    {
      variant: variantProp,
      tooltip,
      tooltipSide = "top",
      icon: Icon,
      children,
      disabled,
      isLoading,
      ...props
    },
    ref
  ) => {
    const context = useTabsContext();
    const variant = variantProp ?? context?.variant ?? "contained";

    const inner = (
      <>
        {Icon && <Icon size={14} className={cn(iconVariants[variant])} />}
        {typeof children === "string" ? <Text>{children}</Text> : children}
        {isLoading && (
          <span
            className="inline-block w-3 h-3 border-2 border-text-03 border-t-transparent rounded-full animate-spin"
            aria-label="Loading"
          />
        )}
      </>
    );

    const trigger = (
      <TabsPrimitive.Trigger
        ref={ref}
        disabled={disabled}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-08",
          triggerBaseStyles[variant],
          variant === "contained" && [
            "data-[state=active]:bg-background-neutral-00",
            "data-[state=active]:text-text-04",
            "data-[state=active]:shadow-01",
            "data-[state=active]:border",
            "data-[state=active]:border-border-01",
          ],
          variant === "pill" && [
            "data-[state=active]:bg-background-tint-inverted-03",
            "data-[state=active]:text-text-inverted-05",
          ],
          variant === "contained" && [
            "data-[state=inactive]:text-text-03",
            "data-[state=inactive]:bg-transparent",
            "data-[state=inactive]:border",
            "data-[state=inactive]:border-transparent",
          ],
          variant === "pill" && [
            "data-[state=inactive]:bg-transparent",
            "data-[state=inactive]:text-text-03",
          ]
        )}
        {...props}
      >
        {tooltip && !disabled ? (
          <SimpleTooltip tooltip={tooltip} side={tooltipSide}>
            {inner}
          </SimpleTooltip>
        ) : (
          inner
        )}
      </TabsPrimitive.Trigger>
    );

    // Disabled native buttons don't emit pointer/focus events, so tooltips
    // inside them won't trigger. Wrap the entire trigger with a neutral span
    // only when disabled so layout stays unchanged for the enabled case.
    if (tooltip && disabled) {
      return (
        <SimpleTooltip tooltip={tooltip} side={tooltipSide}>
          <span className="flex-1 inline-flex align-middle justify-center">
            {trigger}
          </span>
        </SimpleTooltip>
      );
    }

    return trigger;
  }
);
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

/* -------------------------------------------------------------------------- */

/**
 * Tabs Content Component
 *
 * Container for the content associated with each tab.
 * Only the content for the active tab is rendered and visible.
 *
 * @param value - The tab value this content is associated with (must match a Tabs.Trigger value)
 */
const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  SectionProps & { value: string }
>(({ children, value, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    value={value}
    className="pt-4 focus:outline-none focus:border-theme-primary-05 w-full"
  >
    <Section padding={0} {...props}>
      {children}
    </Section>
  </TabsPrimitive.Content>
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

/* =============================================================================
   EXPORTS
   ============================================================================= */

export default Object.assign(TabsRoot, {
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
});
