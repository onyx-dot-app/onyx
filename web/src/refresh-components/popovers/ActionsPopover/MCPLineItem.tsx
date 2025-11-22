"use client";

import React from "react";
import {
  MCPAuthenticationType,
  MCPAuthenticationPerformer,
  ToolSnapshot,
} from "@/lib/tools/interfaces";
import SvgKey from "@/icons/key";
import SvgLock from "@/icons/lock";
import SvgCheck from "@/icons/check";
import SvgServer from "@/icons/server";
import SvgChevronRight from "@/icons/chevron-right";
import LineItem from "@/refresh-components/buttons/LineItem";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { cn, noProp } from "@/lib/utils";
import { SvgProps } from "@/icons";

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
  const showInlineReauth =
    showAuthTrigger && isAuthenticated && tools.length > 0;
  const showReauthButton = showAuthTrigger && !showInlineReauth;

  function getServerIcon(): React.FunctionComponent<SvgProps> {
    if (isLoading) return SimpleLoader;
    if (isAuthenticated) {
      return (({ className }) => (
        <SvgCheck className={cn(className, "stroke-status-success-05")} />
      )) as React.FunctionComponent<SvgProps>;
    }
    if (server.auth_type === MCPAuthenticationType.NONE) return SvgServer;
    if (server.auth_performer === MCPAuthenticationPerformer.PER_USER) {
      return (({ className }) => (
        <SvgKey className={cn(className, "stroke-status-warning-05")} />
      )) as React.FunctionComponent<SvgProps>;
    }
    return (({ className }) => (
      <SvgLock className={cn(className, "stroke-status-error-05")} />
    )) as React.FunctionComponent<SvgProps>;
  }

  const handleClick = noProp(() => {
    if (isAuthenticated && tools.length > 0) {
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
      forced={isActive}
      rightChildren={
        <div className="flex flex-row items-center gap-1">
          {isAuthenticated &&
            tools.length > 0 &&
            enabledTools.length > 0 &&
            tools.length !== enabledTools.length && (
              <div className="flex flex-row items-center gap-1">
                <Text secondaryBody nowrap className="text-action-link-05">
                  {enabledTools.length}
                </Text>
                <Text secondaryBody nowrap>
                  {` of ${tools.length}`}
                </Text>
              </div>
            )}
          {showInlineReauth && (
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
