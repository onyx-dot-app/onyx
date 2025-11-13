"use client";

import React from "react";
import { cn } from "@/lib/utils";
import SvgServer from "@/icons/server";
import { MCPActionCardHeader } from "./MCPActionCardHeader";
import { MCPActionCardActions } from "./MCPActionCardActions";
import { ToolsSection } from "./ToolsSection";

export type MCPActionStatus = "connected" | "pending" | "disconnected";

export interface MCPActionCardProps {
  // Core content
  title: string;
  description: string;
  logo?: React.ReactNode;

  // Status
  status?: MCPActionStatus;

  // Tool count (only for connected state)
  toolCount?: number;

  // Actions
  onDisconnect?: () => void;
  onManage?: () => void;
  onViewTools?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onAuthenticate?: () => void; // For pending state
  onReconnect?: () => void; // For disconnected state

  // Optional styling
  className?: string;
}

// Main Component
export default function MCPActionCard({
  title,
  description,
  logo,
  status = "connected",
  toolCount,
  onDisconnect,
  onManage,
  onViewTools,
  onEdit,
  onDelete,
  onAuthenticate,
  onReconnect,
  className,
}: MCPActionCardProps) {
  const isConnected = status === "connected";

  const icon = isConnected ? (
    logo
  ) : (
    <SvgServer className="h-5 w-5 stroke-text-04" aria-hidden="true" />
  );

  return (
    <div
      className={cn(
        "flex flex-col p-2 w-full",
        isConnected && "bg-background-tint-00 border-b border-border-01",
        className
      )}
      role="article"
      aria-label={`${title} MCP server card`}
    >
      {/* Header Section */}
      <div className="flex items-start justify-between w-full">
        <MCPActionCardHeader
          title={title}
          description={description}
          icon={icon}
          status={status}
          onEdit={onEdit}
        />

        {/* Action Buttons */}
        <MCPActionCardActions
          status={status}
          serverName={title}
          onDisconnect={onDisconnect}
          onManage={onManage}
          onAuthenticate={onAuthenticate}
          onReconnect={onReconnect}
          onDelete={onDelete}
        />
      </div>

      {/* Tools Section (Connected state only) */}
      {isConnected && (
        <ToolsSection
          serverName={title}
          toolCount={toolCount}
          onViewTools={onViewTools}
        />
      )}
    </div>
  );
}
