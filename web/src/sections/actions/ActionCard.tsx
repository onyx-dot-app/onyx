"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import ActionCardHeader from "@/sections/actions/ActionCardHeader";
import ToolsSection from "@/sections/actions/ToolsSection";
import { cn } from "@opal/utils";
import { ActionStatus } from "@/lib/tools/types";
import type { IconProps, RichStr } from "@opal/types";
import { SvgServer } from "@opal/icons";
import { SelectCard } from "@opal/components";
import { Hoverable } from "@opal/core";

const CARD_CONTROL_SELECTOR =
  "button, a, input, textarea, select, [role='button'], [role='switch'], [contenteditable='true']";

export interface ActionCardProps {
  // Core content
  title: string;
  description: string;
  icon?: React.FunctionComponent<IconProps>;

  // Status
  status: ActionStatus;
  pendingDescription?: string | RichStr;

  // Header actions (right side of header)
  actions: React.ReactNode;
  footer?: React.ReactNode;

  // Optional card action; nested controls and expanded tools keep their own actions.
  onActivate?: () => void;

  // Rename handler for header
  onRename?: (newName: string) => Promise<void>;

  // Expansion is controlled by the server or action card.
  isExpanded?: boolean;

  // Search functionality
  enableSearch?: boolean;
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;

  // Tools section actions
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
  pendingDescription,
  actions,
  footer,
  onActivate,
  onRename,
  isExpanded = false,
  enableSearch = false,
  searchQuery = "",
  onSearchQueryChange,
  onFold,
  children,
  ariaLabel,
  className,
}: ActionCardProps) {
  const t = useTranslations("actions");
  const [isControlHovered, setIsControlHovered] = useState(false);
  const [isCardKeyboardFocused, setIsCardKeyboardFocused] = useState(false);

  const isConnected = status === ActionStatus.CONNECTED;
  const isDisconnected = status === ActionStatus.DISCONNECTED;

  const backgroundColor = isConnected
    ? "bg-background-tint-00"
    : isDisconnected
      ? "bg-background-neutral-02"
      : "";

  const header = (
    <div className="flex items-start justify-between gap-2 p-3 w-full min-w-0">
      <ActionCardHeader
        title={title}
        description={description}
        icon={icon || SvgServer}
        status={status}
        pendingDescription={pendingDescription}
        showStatus={!footer}
        onRename={onRename}
      />
      <div className="shrink-0 flex items-start">{actions}</div>
    </div>
  );

  const expandedContent = (
    <>
      {enableSearch && (
        <ToolsSection
          onFold={onFold}
          searchQuery={searchQuery}
          onSearchQueryChange={onSearchQueryChange || (() => {})}
        />
      )}
      {children && (
        <div className="p-2 border-t border-border-01">{children}</div>
      )}
    </>
  );

  return (
    <Hoverable.Root group="action-card">
      {onActivate ? (
        <div
          className={cn(
            "w-full min-w-0 rounded-16",
            backgroundColor,
            className
          )}
        >
          <SelectCard
            expandable
            expanded={isExpanded}
            expandedContent={expandedContent}
            expandableContentHeight="full"
            state={isConnected ? "filled" : "empty"}
            passive={isControlHovered && !isCardKeyboardFocused}
            onPointerOver={(event) => {
              const target = event.target;
              setIsControlHovered(
                target instanceof Element &&
                  !!target.closest(CARD_CONTROL_SELECTOR)
              );
            }}
            onPointerLeave={() => setIsControlHovered(false)}
            onFocusCapture={(event) =>
              setIsCardKeyboardFocused(
                event.target === event.currentTarget &&
                  event.currentTarget.matches(":focus-visible")
              )
            }
            onBlurCapture={() => setIsCardKeyboardFocused(false)}
            padding={0}
            rounding={4}
            role="article"
            aria-label={ariaLabel || t("actionCard.card.ariaLabel", { title })}
            onClick={(event) => {
              const target = event.target;
              if (
                !(target instanceof Element) ||
                !event.currentTarget.contains(target)
              )
                return;
              if (target.closest(CARD_CONTROL_SELECTOR)) return;
              onActivate();
            }}
          >
            {header}
            {footer}
          </SelectCard>
        </div>
      ) : (
        <div
          className={cn(
            "w-full min-w-0",
            backgroundColor,
            "border border-border-01 rounded-16",
            "transition-shadow duration-200",
            "hover:shadow-box-00",
            className
          )}
          role="article"
          aria-label={ariaLabel || t("actionCard.card.ariaLabel", { title })}
        >
          {header}
          {footer}
          {isExpanded && expandedContent}
        </div>
      )}
    </Hoverable.Root>
  );
}
