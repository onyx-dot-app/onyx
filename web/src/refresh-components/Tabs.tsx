"use client";

import React, { useRef, useState, useEffect } from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { WithoutStyles } from "@/types";
import { Section, SectionProps } from "@/layouts/general-layouts";
import { IconProps } from "@opal/types";
import Text from "./texts/Text";

/**
 * Tabs Root Component
 *
 * Container for tab navigation and content. Manages the active tab state.
 *
 * @param defaultValue - The tab value that should be active by default (uncontrolled)
 * @param value - The controlled active tab value
 * @param onValueChange - Callback when the active tab changes
 *
 * @example
 * ```tsx
 * // Uncontrolled tabs (state managed internally)
 * <Tabs defaultValue="account">
 *   <Tabs.List>
 *     <Tabs.Trigger value="account">Account</Tabs.Trigger>
 *     <Tabs.Trigger value="password">Password</Tabs.Trigger>
 *   </Tabs.List>
 *   <Tabs.Content value="account">Account settings content</Tabs.Content>
 *   <Tabs.Content value="password">Password settings content</Tabs.Content>
 * </Tabs>
 *
 * // Controlled tabs (explicit state management)
 * <Tabs value={activeTab} onValueChange={setActiveTab}>
 *   <Tabs.List>
 *     <Tabs.Trigger value="tab1">Tab 1</Tabs.Trigger>
 *     <Tabs.Trigger value="tab2">Tab 2</Tabs.Trigger>
 *   </Tabs.List>
 *   <Tabs.Content value="tab1">Content 1</Tabs.Content>
 *   <Tabs.Content value="tab2">Content 2</Tabs.Content>
 * </Tabs>
 * ```
 */
const TabsRoot = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Root>,
  WithoutStyles<React.ComponentPropsWithoutRef<typeof TabsPrimitive.Root>>
>(({ ...props }, ref) => (
  <TabsPrimitive.Root ref={ref} className="w-full" {...props} />
));
TabsRoot.displayName = TabsPrimitive.Root.displayName;

/**
 * Tabs List Props
 */
interface TabsListProps
  extends WithoutStyles<
    React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
  > {
  /** Visual variant of the tabs list
   * - 'contained': Grid layout with background (default)
   * - 'pill': Flex layout with bottom line indicator
   */
  variant?: "contained" | "pill";
  /** Content to render on the right side of the tab list (pill variant only) */
  rightContent?: React.ReactNode;
}

/**
 * Tabs List Component
 *
 * Container for tab triggers. Renders as a horizontal list with pill-style background.
 * Automatically manages keyboard navigation (arrow keys) and accessibility attributes.
 *
 * @param variant - Visual variant: 'contained' (default) or 'pill'
 *
 * @example
 * ```tsx
 * // Contained variant (default)
 * <Tabs defaultValue="overview">
 *   <Tabs.List>
 *     <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
 *     <Tabs.Trigger value="analytics">Analytics</Tabs.Trigger>
 *     <Tabs.Trigger value="settings">Settings</Tabs.Trigger>
 *   </Tabs.List>
 *   <Tabs.Content value="overview">...</Tabs.Content>
 * </Tabs>
 *
 * // Pill variant
 * <Tabs defaultValue="search">
 *   <Tabs.List variant="pill">
 *     <Tabs.Trigger value="search" variant="pill">Search</Tabs.Trigger>
 *     <Tabs.Trigger value="browse" variant="pill">Browse</Tabs.Trigger>
 *   </Tabs.List>
 * </Tabs>
 * ```
 *
 * @remarks
 * - Contained: rounded pill background with grid layout
 * - Pill: transparent background with bottom line indicator
 * - Supports keyboard navigation (Left/Right arrows, Home/End keys)
 */
const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  TabsListProps
>(({ variant = "contained", rightContent, children, ...props }, ref) => {
  const internalRef = useRef<HTMLDivElement>(null);
  const [indicatorStyle, setIndicatorStyle] = useState({
    left: 0,
    width: 0,
    opacity: 0,
  });

  // Update indicator position when active tab changes (pill variant only)
  useEffect(() => {
    if (variant !== "pill") return;

    const updateIndicator = () => {
      const list = internalRef.current;
      if (!list) return;

      const activeTab = list.querySelector<HTMLElement>(
        '[data-state="active"]'
      );
      if (activeTab) {
        const listRect = list.getBoundingClientRect();
        const tabRect = activeTab.getBoundingClientRect();
        setIndicatorStyle({
          left: tabRect.left - listRect.left,
          width: tabRect.width,
          opacity: 1,
        });
      }
    };

    updateIndicator();

    // Use MutationObserver to detect tab changes
    const observer = new MutationObserver(updateIndicator);
    if (internalRef.current) {
      observer.observe(internalRef.current, {
        attributes: true,
        subtree: true,
        attributeFilter: ["data-state"],
      });
    }

    return () => observer.disconnect();
  }, [variant]);

  return (
    <TabsPrimitive.List
      ref={(node) => {
        internalRef.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      }}
      className={cn(
        // Contained variant (default)
        variant === "contained" &&
          "grid w-full rounded-08 bg-background-tint-03",
        // Pill variant
        variant === "pill" &&
          "relative flex items-center pb-[4px] bg-background-tint-00"
      )}
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
      {/* Tabs container */}
      {variant === "pill" ? (
        <div className="flex items-center gap-2">{children}</div>
      ) : (
        children
      )}

      {/* Right action slot for pill variant */}
      {variant === "pill" && rightContent && (
        <div className="ml-auto pl-2">{rightContent}</div>
      )}

      {/* Full-width subtle line for pill variant */}
      {variant === "pill" && (
        <div className="absolute bottom-0 left-0 right-0 h-px bg-border-02 pointer-events-none" />
      )}

      {/* Sliding active indicator for pill variant */}
      {variant === "pill" && (
        <div
          className="absolute bottom-0 h-[2px] bg-background-tint-inverted-03 z-10 transition-all duration-200 ease-out pointer-events-none"
          style={{
            left: indicatorStyle.left,
            width: indicatorStyle.width,
            opacity: indicatorStyle.opacity,
          }}
        />
      )}
    </TabsPrimitive.List>
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

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
  /** Visual variant of the tab trigger (should match parent TabsList variant)
   * - 'contained': Background-based active state (default)
   * - 'pill': Dark pill with bottom line indicator
   */
  variant?: "contained" | "pill";
  /** Optional tooltip text to display on hover */
  tooltip?: string;
  /** Side where tooltip appears. Default: "top" */
  tooltipSide?: "top" | "bottom" | "left" | "right";

  icon?: React.FunctionComponent<IconProps>;
  /** Tab label - can be string or ReactNode (for custom content like icon + text) */
  children?: React.ReactNode;
  /** Show loading spinner after label */
  isLoading?: boolean;
}

/**
 * Tabs Trigger Component
 *
 * Individual tab button that switches the active tab when clicked.
 * Supports tooltips and disabled state with special tooltip handling.
 *
 * @param value - Unique value identifying this tab (required)
 * @param tooltip - Optional tooltip text shown on hover
 * @param tooltipSide - Side where tooltip appears (top, bottom, left, right). Default: "top"
 * @param disabled - Whether the tab is disabled
 *
 * @example
 * ```tsx
 * // Basic tabs
 * <Tabs.List>
 *   <Tabs.Trigger value="home">Home</Tabs.Trigger>
 *   <Tabs.Trigger value="profile">Profile</Tabs.Trigger>
 * </Tabs.List>
 *
 * // With tooltips
 * <Tabs.List>
 *   <Tabs.Trigger value="edit" tooltip="Edit document">
 *     <SvgEdit />
 *   </Tabs.Trigger>
 *   <Tabs.Trigger value="share" tooltip="Share with others" tooltipSide="bottom">
 *     <SvgShare />
 *   </Tabs.Trigger>
 * </Tabs.List>
 *
 * // With disabled state and tooltip
 * <Tabs.List>
 *   <Tabs.Trigger value="admin" disabled tooltip="Admin access required">
 *     Admin Panel
 *   </Tabs.Trigger>
 * </Tabs.List>
 * ```
 *
 * @remarks
 * - Active state: white background with shadow
 * - Inactive state: transparent with hover effect
 * - Disabled state: reduced opacity, no pointer events
 * - Tooltips work on both enabled and disabled triggers
 * - Disabled triggers require special tooltip wrapping to show tooltips
 * - Automatic focus management and keyboard navigation
 */
const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  TabsTriggerProps
>(
  (
    {
      variant = "contained",
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
    const inner = (
      <>
        {Icon && (
          <Icon
            size={14}
            className={cn(
              variant === "contained" && "stroke-text-03",
              variant === "pill" && "stroke-current"
            )}
          />
        )}
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

          // Contained variant (default)
          variant === "contained" && [
            "p-2 gap-2",
            "data-[state=active]:bg-background-neutral-00 data-[state=active]:text-text-04 data-[state=active]:shadow-01 data-[state=active]:border",
            "data-[state=inactive]:text-text-03 data-[state=inactive]:bg-transparent data-[state=inactive]:border data-[state=inactive]:border-transparent",
          ],

          // Pill variant - 12px text, smooth transitions
          variant === "pill" && [
            "p-1.5 font-secondary-action",
            "transition-all duration-200 ease-out",
            "data-[state=active]:bg-background-tint-inverted-03 data-[state=active]:text-text-inverted-05",
            "data-[state=inactive]:bg-transparent data-[state=inactive]:text-text-03",
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

    // Disabled native buttons don't emit pointer/focus events, so tooltips inside
    // them won't trigger. Wrap the *entire* trigger with a neutral span only when
    // disabled so layout stays unchanged for the enabled case.
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

/**
 * Tabs Content Component
 *
 * Container for the content associated with each tab.
 * Only the content for the active tab is rendered and visible.
 *
 * @param value - The tab value this content is associated with (must match a Tabs.Trigger value)
 *
 * @example
 * ```tsx
 * <Tabs defaultValue="details">
 *   <Tabs.List>
 *     <Tabs.Trigger value="details">Details</Tabs.Trigger>
 *     <Tabs.Trigger value="logs">Logs</Tabs.Trigger>
 *   </Tabs.List>
 *
 *   <Tabs.Content value="details">
 *     <Section>
 *       <Text>Detailed information goes here</Text>
 *     </Section>
 *   </Tabs.Content>
 *
 *   <Tabs.Content value="logs">
 *     <Section>
 *       <LogViewer logs={logs} />
 *     </Section>
 *   </Tabs.Content>
 * </Tabs>
 * ```
 *
 * @remarks
 * - Content is only mounted/visible when its associated tab is active
 * - Default top margin of 0.5rem (mt-2) to separate from tabs
 * - Supports focus management for accessibility
 * - Custom className can override default styling
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

export default Object.assign(TabsRoot, {
  List: TabsList,
  Trigger: TabsTrigger,
  Content: TabsContent,
});
