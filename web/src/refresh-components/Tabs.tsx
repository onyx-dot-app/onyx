"use client";

import React, {
  useRef,
  useState,
  useEffect,
  useMemo,
  useCallback,
} from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn, mergeRefs } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { WithoutStyles } from "@/types";
import { Section, SectionProps } from "@/layouts/general-layouts";
import { IconProps } from "@opal/types";
import { SvgChevronLeft, SvgChevronRight } from "@opal/icons";
import Text from "./texts/Text";
import IconButton from "./buttons/IconButton";

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
  pill: "relative flex w-full items-center pb-[5px] bg-background-tint-00 overflow-hidden",
} as const;

/** Base style classes for TabsTrigger variants */
const triggerBaseStyles = {
  contained: "p-2 gap-2",
  pill: "p-1 font-secondary-action transition-all duration-200 ease-out",
} as const;

/** Icon style classes for TabsTrigger variants */
const iconVariants = {
  contained: "stroke-text-03",
  pill: "stroke-current",
} as const;

/* =============================================================================
   CONSTANTS
   ============================================================================= */

/** Pixel tolerance for detecting scroll boundaries (accounts for rounding) */
const SCROLL_TOLERANCE_PX = 1;

/** Pixel amount to scroll when clicking scroll arrows */
const SCROLL_AMOUNT_PX = 200;

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
  enabled: boolean,
  scrollContainerRef?: React.RefObject<HTMLElement | null>
): { style: IndicatorStyle; isScrolling: boolean } {
  const [style, setStyle] = useState<IndicatorStyle>({
    left: 0,
    width: 0,
    opacity: 0,
  });
  const [isScrolling, setIsScrolling] = useState(false);
  const scrollTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const list = listRef.current;
    if (!list) return;

    const updateIndicator = () => {
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

    const handleScroll = () => {
      setIsScrolling(true);
      updateIndicator();

      // Clear existing timeout
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
      // Reset scrolling state after scroll ends
      scrollTimeoutRef.current = setTimeout(() => {
        setIsScrolling(false);
      }, 150);
    };

    updateIndicator();

    // Watch for size changes on ANY tab (sibling size changes affect active tab position)
    const resizeObserver = new ResizeObserver(() => updateIndicator());
    list.querySelectorAll<HTMLElement>('[role="tab"]').forEach((tab) => {
      resizeObserver.observe(tab);
    });

    // Watch for data-state changes (tab switches)
    const mutationObserver = new MutationObserver(() => updateIndicator());
    mutationObserver.observe(list, {
      attributes: true,
      subtree: true,
      attributeFilter: ["data-state"],
    });

    // Listen for scroll events on scroll container
    const scrollContainer = scrollContainerRef?.current;
    if (scrollContainer) {
      scrollContainer.addEventListener("scroll", handleScroll);
    }

    return () => {
      mutationObserver.disconnect();
      resizeObserver.disconnect();
      if (scrollContainer) {
        scrollContainer.removeEventListener("scroll", handleScroll);
      }
      if (scrollTimeoutRef.current) {
        clearTimeout(scrollTimeoutRef.current);
      }
    };
  }, [enabled, listRef, scrollContainerRef]);

  return { style, isScrolling };
}

/** State for horizontal scroll arrows */
interface ScrollState {
  canScrollLeft: boolean;
  canScrollRight: boolean;
  scrollLeft: () => void;
  scrollRight: () => void;
}

/**
 * Hook to manage horizontal scrolling with arrow navigation.
 *
 * Tracks scroll position and overflow state of a container, providing
 * scroll functions and boolean flags for arrow visibility.
 *
 * @param containerRef - Ref to the scrollable container element
 * @param enabled - Whether scroll tracking is enabled
 * @returns Object with canScrollLeft, canScrollRight, and scroll functions
 */
function useHorizontalScroll(
  containerRef: React.RefObject<HTMLElement | null>,
  enabled: boolean
): ScrollState {
  const [canScrollLeft, setCanScrollLeft] = useState(false);
  const [canScrollRight, setCanScrollRight] = useState(false);

  const updateScrollState = useCallback(() => {
    const container = containerRef.current;
    if (!container) return;

    const { scrollLeft, scrollWidth, clientWidth } = container;
    setCanScrollLeft(scrollLeft > 0);
    setCanScrollRight(
      scrollLeft + clientWidth < scrollWidth - SCROLL_TOLERANCE_PX
    );
  }, [containerRef]);

  useEffect(() => {
    if (!enabled) return;

    const container = containerRef.current;
    if (!container) return;

    // Delay initial measurement until after layout
    const rafId = requestAnimationFrame(() => {
      updateScrollState();
    });

    container.addEventListener("scroll", updateScrollState);

    const resizeObserver = new ResizeObserver(updateScrollState);
    resizeObserver.observe(container);

    // Also observe children for size changes
    Array.from(container.children).forEach((child) => {
      resizeObserver.observe(child);
    });

    return () => {
      cancelAnimationFrame(rafId);
      container.removeEventListener("scroll", updateScrollState);
      resizeObserver.disconnect();
    };
  }, [enabled, containerRef, updateScrollState]);

  const scrollLeft = useCallback(() => {
    containerRef.current?.scrollBy({
      left: -SCROLL_AMOUNT_PX,
      behavior: "smooth",
    });
  }, [containerRef]);

  const scrollRight = useCallback(() => {
    containerRef.current?.scrollBy({
      left: SCROLL_AMOUNT_PX,
      behavior: "smooth",
    });
  }, [containerRef]);

  return { canScrollLeft, canScrollRight, scrollLeft, scrollRight };
}

/* =============================================================================
   SUB-COMPONENTS
   ============================================================================= */

/**
 * Renders the bottom line and sliding indicator for the pill variant.
 * The indicator animates smoothly when switching between tabs.
 *
 * @param style - Position and opacity for the sliding indicator
 * @param rightOffset - Distance from the right edge where the border line should stop (for rightContent)
 */
function PillIndicator({
  style,
  rightOffset = 0,
}: {
  style: IndicatorStyle;
  rightOffset?: number;
}) {
  return (
    <>
      <div
        className="absolute bottom-0 left-0 h-px bg-border-02 pointer-events-none"
        style={{ right: rightOffset }}
      />
      <div
        className="absolute bottom-0 h-[2px] bg-background-tint-inverted-03 z-10 pointer-events-none transition-all duration-200 ease-out"
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
  extends Omit<
    React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>,
    "style"
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

  /**
   * Enable horizontal scroll arrows when tabs overflow.
   * Only applies to the `pill` variant.
   * @default false
   */
  enableScrollArrows?: boolean;
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
>(
  (
    {
      variant = "contained",
      rightContent,
      enableScrollArrows = false,
      children,
      className,
      ...props
    },
    ref
  ) => {
    const listRef = useRef<HTMLDivElement>(null);
    const tabsContainerRef = useRef<HTMLDivElement>(null);
    const scrollArrowsRef = useRef<HTMLDivElement>(null);
    const rightContentRef = useRef<HTMLDivElement>(null);
    const [rightOffset, setRightOffset] = useState(0);
    const isPill = variant === "pill";
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

    // Track right content and scroll arrows width to offset the border line
    useEffect(() => {
      if (!isPill) {
        setRightOffset(0);
        return;
      }

      const updateWidth = () => {
        let totalWidth = 0;

        // Add scroll arrows width if visible
        if (scrollArrowsRef.current) {
          totalWidth += scrollArrowsRef.current.offsetWidth;
        }

        // Add right content width if present
        if (rightContentRef.current) {
          totalWidth += rightContentRef.current.offsetWidth;
        }

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
        className={cn(listVariants[variant], className)}
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
            enableScrollArrows ? (
              <div
                ref={tabsContainerRef}
                className="flex items-center gap-2 overflow-x-auto scrollbar-hide flex-1 min-w-0"
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
              className="flex items-center gap-1 pl-2 flex-shrink-0"
            >
              <IconButton
                main
                internal
                icon={SvgChevronLeft}
                onClick={handleScrollLeft}
                disabled={!canScrollLeft}
                tooltip="Scroll tabs left"
              />
              <IconButton
                main
                internal
                icon={SvgChevronRight}
                onClick={handleScrollRight}
                disabled={!canScrollRight}
                tooltip="Scroll tabs right"
              />
            </div>
          )}

          {isPill && rightContent && (
            <div ref={rightContentRef} className="ml-auto flex-shrink-0">
              {rightContent}
            </div>
          )}

          {isPill && (
            <PillIndicator style={indicatorStyle} rightOffset={rightOffset} />
          )}
        </TabsContext.Provider>
      </TabsPrimitive.List>
    );
  }
);
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
        {Icon && (
          <div className="p-0.5">
            <Icon size={14} className={cn(iconVariants[variant])} />
          </div>
        )}
        {typeof children === "string" ? <Text>{children}</Text> : children}
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
            "data-[state=inactive]:bg-background-tint-00",
            "data-[state=inactive]:text-text-03",
          ]
        )}
        {...props}
      >
        {tooltip && !disabled ? (
          <SimpleTooltip tooltip={tooltip} side={tooltipSide}>
            <span className="inline-flex items-center gap-inherit">
              {inner}
            </span>
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
