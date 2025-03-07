"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "@/lib/utils";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.List
    ref={ref}
    className={cn(
      [
        "inline-flex",
        "flex w-full",
        "items-center",
        "justify-center",
        "bg-neutral-150",
        "text-neutral-500",
        "dark:bg-neutral-800",
        "dark:text-neutral-400",
        "rounded-t-lg",
      ].join(" "),
      className
    )}
    {...props}
  />
));
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      [
        "relative",
        "justify-center",
        "flex w-full",
        "border-b",
        "data-[state=active]:border-t",
        "data-[state=active]:border-l",
        "data-[state=active]:border-r",
        "data-[state=active]:border-b-0",
        "p-2",
        "data-[state=active]:bg-white",
        "data-[state=active]:rounded-t-lg",
        "data-[state=active]:shadow-[3px_-3px_6px_-3px_rgba(0,0,0,0.15)]",
      ].join(" "),
      className
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ElementRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      [
        "mt-2",
        "ring-offset-background",
        "focus-visible:outline-none",
        "focus-visible:ring-2",
        "focus-visible:ring-text-950",
        "focus-visible:ring-offset-2",
        "dark:ring-offset-background-950",
        "dark:focus-visible:ring-text-300",
        "border-l",
        "border-r",
        "border-b",
        "px-6 pt-6 pb-3",
        "-mt-px",
        "rounded-b-lg",
        "shadow-[3px_-4px_6px_-3px_rgba(0,0,0,0.15)]",
      ].join(" "),
      className
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
