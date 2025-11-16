"use client";

import React from "react";
import { cn } from "@/lib/utils";
import SvgServer from "@/icons/server";
import ActionCardHeader from "./ActionCardHeader";
import MCPActions from "./MCPActions";
import ToolsSection from "./ToolsSection";
import type { Tool } from "./ToolsList";

import type { MCPActionStatus } from "./types";
import CardSection from "@/components/admin/CardSection";

export interface ActionCardProps {
  // Core content
  title: string;
  description: string;
  logo?: React.ReactNode;

  // Status
  status?: MCPActionStatus;

  // Tool count (only for connected state)
  toolCount?: number;

  // Tools (optional - for expanded view)
  tools?: Tool[];

  // Actions
  onDisconnect?: () => void;
  onManage?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onAuthenticate?: () => void; // For pending state
  onReconnect?: () => void; // For disconnected state

  // Tool-related actions
  onToolToggle?: (toolId: string, enabled: boolean) => void;
  onRefreshTools?: () => void;
  onDisableAllTools?: () => void;

  // Optional styling
  className?: string;
}

// Main Component
export default function ActionCard({
  title,
  description,
  logo,
  status = "connected",
  toolCount,
  tools,
  onDisconnect,
  onManage,
  onEdit,
  onDelete,
  onAuthenticate,
  onReconnect,
  onToolToggle,
  onRefreshTools,
  onDisableAllTools,
  className,
}: ActionCardProps) {
  const isConnected = status === "connected";
  const isPending = status === "pending";
  const isDisconnected = status === "disconnected";

  const icon = isConnected ? (
    logo
  ) : (
    <SvgServer className="h-5 w-5 stroke-text-04" aria-hidden="true" />
  );

  const backgroundColor = isConnected
    ? "bg-background-tint-00"
    : isDisconnected
      ? "bg-background-neutral-02"
      : "";

  const showToolsSection = isConnected || isDisconnected;

  return (
    <CardSection
      className={cn(
        "flex flex-col p-2 w-full",
        backgroundColor,
        "border border-border-01",
        className
      )}
      role="article"
      aria-label={`${title} MCP server card`}
    >
      {/* Header Section */}
      <div className="flex items-start justify-between w-full">
        <ActionCardHeader
          title={title}
          description={description}
          icon={icon}
          status={status}
          onEdit={onEdit}
        />

        {/* Action Buttons */}
        <MCPActions
          status={status}
          serverName={title}
          onDisconnect={onDisconnect}
          onManage={onManage}
          onAuthenticate={onAuthenticate}
          onReconnect={onReconnect}
          onDelete={onDelete}
        />
      </div>

      {/* Tools Section (Connected/Disconnected state only) */}
      {showToolsSection && (
        <ToolsSection
          serverName={title}
          toolCount={toolCount}
          tools={tools}
          onToolToggle={onToolToggle}
          onRefresh={onRefreshTools}
          onDisableAll={onDisableAllTools}
        />
      )}
    </CardSection>
  );
}
