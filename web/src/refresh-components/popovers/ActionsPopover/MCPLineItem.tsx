"use client";

import React from "react";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  ToolSnapshot,
} from "@/lib/tools/interfaces";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { cn, noProp } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import {
  SvgCheck,
  SvgChevronRight,
  SvgKey,
  SvgLock,
  SvgServer,
} from "@opal/icons";

export interface MCPServer {
  id: number;
  name: string;
  owner_email: string;
  server_url: string;
  auth_type: MCPAuthenticationType;
  auth_performer: MCPAuthenticationPerformer;
  is_authenticated: boolean;
  user_authenticated?: boolean;
  auth_template?: any;
  user_credentials?: Record<string, string>;
}

export interface MCPLineItemProps {
  server: MCPServer;
  isActive: boolean;
  onSelect: () => void;
  onAuthenticate: () => void;
  tools: ToolSnapshot[];
  enabledTools: ToolSnapshot[];
  isAuthenticated: boolean;
  isLoading: boolean;
}

export default function MCPLineItem({
  server,
  isActive,
  onSelect,
  onAuthenticate,
  tools,
  enabledTools,
  isAuthenticated,
  isLoading,
}: MCPLineItemProps) {
  const showAuthTrigger =
    server.auth_performer === MCPAuthenticationPerformer.PER_USER &&
    server.auth_type !== MCPAuthenticationType.NONE;

  const canClickIntoServer = isAuthenticated && tools.length > 0;
  const showInlineReauth = showAuthTrigger && canClickIntoServer;
  const showReauthButton = showAuthTrigger && !showInlineReauth;

  function getServerIcon(): React.FunctionComponent<IconProps> {
    if (isLoading) return SimpleLoader;
    if (isAuthenticated) {
      return (({ className }) => (
        <SvgCheck className={cn(className, "stroke-status-success-05")} />
      )) as React.FunctionComponent<IconProps>;
    }
    if (server.auth_type === MCPAuthenticationType.NONE) return SvgServer;
    if (server.auth_performer === MCPAuthenticationPerformer.PER_USER) {
      return (({ className }) => (
        <SvgKey className={cn(className, "stroke-status-warning-05")} />
      )) as React.FunctionComponent<IconProps>;
    }
    return (({ className }) => (
      <SvgLock className={cn(className, "stroke-status-error-05")} />
    )) as React.FunctionComponent<IconProps>;
  }

  const handleClick = noProp(() => {
    if (canClickIntoServer) {
      onSelect();
      return;
    }
    if (showAuthTrigger) {
      onAuthenticate();
    }
  });

  const allToolsDisabled = enabledTools.length === 0 && tools.length > 0;

  return (
    <LineItem
      data-mcp-server-id={server.id}
      data-mcp-server-name={server.name}
      icon={getServerIcon()}
      onClick={handleClick}
      strikethrough={allToolsDisabled}
      selected={isActive}
      rightChildren={
        <div className="flex flex-row items-center gap-1">
          {isAuthenticated &&
            tools.length > 0 &&
            enabledTools.length > 0 &&
            tools.length !== enabledTools.length && (
              <div className="flex flex-row items-center gap-1">
                <Text
                  as="p"
                  secondaryBody
                  nowrap
                  className="text-action-link-05"
                >
                  {enabledTools.length}
                </Text>
                <Text as="p" secondaryBody nowrap>
                  {` of ${tools.length}`}
                </Text>
              </div>
            )}
          {canClickIntoServer && (
            <SvgChevronRight className="h-3.5 w-3.5 stroke-text-03" />
          )}
          {showReauthButton && (
            <span
              className="inline-flex h-6 w-6 items-center justify-center"
              aria-hidden="true"
            >
              <SvgKey className="h-3.5 w-3.5 stroke-text-03" />
            </span>
          )}
        </div>
      }
    >
      {server.name}
    </LineItem>
  );
}
