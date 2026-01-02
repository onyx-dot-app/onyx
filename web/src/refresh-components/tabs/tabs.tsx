"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      "inline-flex h-10 items-center justify-center rounded-08 bg-background-neutral-02 p-1 text-text-02",
      className
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

type TabsTriggerProps = React.ComponentPropsWithoutRef<
  typeof TabsPrimitive.Trigger
> & {
  tooltip?: string;
  tooltipSide?: "top" | "bottom" | "left" | "right";
};

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  TabsTriggerProps
>(
  (
    { className, tooltip, tooltipSide = "top", children, disabled, ...props },
    ref
  ) => {
    const trigger = (
      <TabsPrimitive.Trigger
        ref={ref}
        disabled={disabled}
        className={cn(
          "inline-flex items-center justify-center whitespace-nowrap rounded-08 px-3 py-1.5 font-main-ui-action",
          "transition-all",
          "focus:outline-none focus:border-theme-primary-05",
          "disabled:pointer-events-none disabled:opacity-50 disabled:text-text-01",
          "hover:bg-background-tint-02 hover:text-text-03",
          "data-[state=active]:bg-background-neutral-00 data-[state=active]:text-text-04 data-[state=active]:shadow-01",
          "data-[state=inactive]:text-text-03",
          className
        )}
        {...props}
      >
        {tooltip && !disabled ? (
          <SimpleTooltip tooltip={tooltip} side={tooltipSide}>
            {children}
          </SimpleTooltip>
        ) : (
          children
        )}
      </TabsPrimitive.Trigger>
    );

    // Disabled native buttons don't emit pointer/focus events, so tooltips inside
    // them won't trigger. Wrap the *entire* trigger with a neutral span only when
    // disabled so layout stays unchanged for the enabled case.
    if (tooltip && disabled) {
      return (
        <SimpleTooltip tooltip={tooltip} side={tooltipSide}>
          <span className="inline-flex align-middle justify-center">
            {trigger}
          </span>
        </SimpleTooltip>
      );
    }

    return trigger;
  }
);
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "mt-2",
      "focus:outline-none focus:border-theme-primary-05",
      className
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
