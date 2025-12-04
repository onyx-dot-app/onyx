"use client";

import React, { useState, useEffect, useRef } from "react";
import ActionCardHeader from "@/sections/actions/ActionCardHeader";
import ToolsSection from "@/sections/actions/ToolsSection";
import { cn } from "@/lib/utils";
import { ActionStatus } from "@/lib/tools/types";

export interface ActionCardProps {
  // Core content
  title: string;
  description: string;
  icon?: React.ReactNode;

  // Status
  status: ActionStatus;

  // Header actions (right side of header)
  actions: React.ReactNode;

  // Edit handler for header
  onEdit?: () => void;

  // Expansion control (can be controlled or uncontrolled)
  initialExpanded?: boolean;
  isExpanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;

  // Search functionality
  enableSearch?: boolean;
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;

  // Tools section actions
  onRefresh?: () => void;
  onDisableAll?: () => void;
  onFold?: () => void;

  // Content
  children?: React.ReactNode;

  // Accessibility
  ariaLabel?: string;

  // Optional styling
  className?: string;
}

// Main Component
export default function ActionCard({
  title,
  description,
  icon,
  status,
  actions,
  onEdit,
  initialExpanded = false,
  isExpanded: controlledIsExpanded,
  onExpandedChange,
  enableSearch = false,
  searchQuery = "",
  onSearchQueryChange,
  onRefresh,
  onDisableAll,
  onFold,
  children,
  ariaLabel,
  className,
}: ActionCardProps) {
  // Internal state for uncontrolled mode
  const [internalExpanded, setInternalExpanded] = useState(initialExpanded);
  const hasInitializedExpansion = useRef(false);

  // Determine if we're in controlled mode
  const isControlled = controlledIsExpanded !== undefined;
  const isExpandedActual = isControlled
    ? controlledIsExpanded
    : internalExpanded;

  // Apply initial expansion only once per component lifetime (uncontrolled mode)
  useEffect(() => {
    if (!isControlled && initialExpanded && !hasInitializedExpansion.current) {
      setInternalExpanded(true);
      hasInitializedExpansion.current = true;
    }
  }, [initialExpanded, isControlled]);

  // Handle expansion change
  const handleExpandedChange = (expanded: boolean) => {
    if (isControlled) {
      onExpandedChange?.(expanded);
    } else {
      setInternalExpanded(expanded);
      onExpandedChange?.(expanded);
    }
  };

  const isConnected = status === ActionStatus.CONNECTED;
  const isDisconnected = status === ActionStatus.DISCONNECTED;

  const backgroundColor = isConnected
    ? "bg-background-tint-00"
    : isDisconnected
      ? "bg-background-neutral-02"
      : "";

  return (
    <div
      className={cn(
        "w-full",
        backgroundColor,
        "border border-border-01 rounded-16",
        className
      )}
      role="article"
      aria-label={ariaLabel || `${title} action card`}
    >
      <div className="flex flex-col w-full">
        {/* Header Section */}
        <div className="flex items-start justify-between p-3 w-full">
          <ActionCardHeader
            title={title}
            description={description}
            icon={icon}
            status={status}
            onEdit={onEdit}
          />

          {/* Action Buttons */}
          {actions}
        </div>

        {/* Tools Section (Only when expanded and search is enabled) */}
        {isExpandedActual && enableSearch && (
          <ToolsSection
            onRefresh={onRefresh}
            onDisableAll={onDisableAll}
            onFold={onFold}
            searchQuery={searchQuery}
            onSearchQueryChange={onSearchQueryChange || (() => {})}
          />
        )}
      </div>

      {/* Content Area - Only render when expanded */}
      {isExpandedActual && children && (
        <div className="animate-in fade-in slide-in-from-top-2 duration-300 p-2 border-t border-border-01">
          {children}
        </div>
      )}
    </div>
  );
}
