"use client";

import React from "react";
import Tabs from "./Tabs";
import { IconProps } from "@opal/types";

/**
 * Tab Definition
 *
 * Defines a single tab with its trigger label and content.
 */
export interface TabDefinition {
  /** Display name for the tab trigger */
  name: string;
  /** Content to render when this tab is active */
  content: React.ReactNode;
  /** Optional icon to display in the tab trigger */
  icon?: React.FunctionComponent<IconProps>;
  /** Optional tooltip text to display on hover */
  tooltip?: string;
  /** Optional tooltip side */
  tooltipSide?: "top" | "bottom" | "left" | "right";
  /** Whether the tab is disabled */
  disabled?: boolean;
}

/**
 * Simple Tabs Props
 */
export interface SimpleTabsProps {
  /** Record of tab definitions, where the key is the tab value */
  tabs: Record<string, TabDefinition>;
  /** The tab value that should be active by default */
  defaultValue?: string;
  /** The controlled active tab value */
  value?: string;
  /** Callback when the active tab changes */
  onValueChange?: (value: string) => void;
}

/**
 * SimpleTabs Component
 *
 * A simplified API for creating tabs when you don't need granular control.
 * For complex use cases, use the base Tabs component with Tabs.List, Tabs.Trigger, and Tabs.Content.
 *
 * @example
 * ```tsx
 * const UserComponent = () => {
 *   const [count, setCount] = useState(0);
 *   return <div>User tab with state: {count}</div>;
 * };
 *
 * const AdminComponent = () => {
 *   return <div>Admin content</div>;
 * };
 *
 * <SimpleTabs
 *   tabs={{
 *     user: {
 *       name: "Users",
 *       content: <UserComponent />,
 *       icon: SvgUser,
 *       tooltip: "Manage users"
 *     },
 *     admin: {
 *       name: "Admin",
 *       content: <AdminComponent />,
 *       icon: SvgSettings
 *     }
 *   }}
 *   defaultValue="user"
 * />
 * ```
 *
 * @remarks
 * - This is a convenience wrapper around the base Tabs component
 * - For complex layouts or custom styling, use Tabs.List, Tabs.Trigger, and Tabs.Content directly
 * - Tab keys become the tab values, so they should be stable and URL-friendly
 * - Content components can use React hooks and maintain their own state
 */
export default function SimpleTabs({
  tabs,
  defaultValue,
  value,
  onValueChange,
}: SimpleTabsProps) {
  const tabEntries = Object.entries(tabs);

  // Use the first tab as default if none specified
  const effectiveDefaultValue = defaultValue ?? tabEntries[0]?.[0];

  return (
    <Tabs
      defaultValue={effectiveDefaultValue}
      value={value}
      onValueChange={onValueChange}
    >
      <Tabs.List>
        {tabEntries.map(([key, tab]) => (
          <Tabs.Trigger
            key={key}
            value={key}
            icon={tab.icon}
            tooltip={tab.tooltip}
            tooltipSide={tab.tooltipSide}
            disabled={tab.disabled}
          >
            {tab.name}
          </Tabs.Trigger>
        ))}
      </Tabs.List>

      {tabEntries.map(([key, tab]) => (
        <Tabs.Content key={key} value={key}>
          {tab.content}
        </Tabs.Content>
      ))}
    </Tabs>
  );
}

/**
 * Helper function to generate tab definitions with type safety
 *
 * This is optional but provides better autocomplete and type checking when defining tabs.
 *
 * @example
 * ```tsx
 * const pageTabs = SimpleTabs.generateTabs({
 *   userTab: {
 *     name: "Some name",
 *     content: <SomeComponent />
 *   },
 *   anothaOne: {
 *     name: "DJ Khalid",
 *     content: <AnothaOne />
 *   }
 * });
 *
 * <SimpleTabs tabs={pageTabs} />
 * ```
 */
SimpleTabs.generateTabs = <T extends Record<string, TabDefinition>>(
  tabs: T
): T => tabs;
