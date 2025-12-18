"use client";
import { ActionStatus } from "@/lib/tools/interfaces";
import React from "react";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgArrowExchange,
  SvgChevronDown,
  SvgPlug,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { useActionCardContext } from "@/sections/actions/ActionCardContext";
import { cn } from "@/lib/utils";

interface ActionsProps {
  status: ActionStatus;
  serverName: string;
  onDisconnect?: () => void;
  onManage?: () => void;
  onAuthenticate?: () => void;
  onReconnect?: () => void;
  onDelete?: () => void;
  toolCount?: number;
  isToolsExpanded?: boolean;
  onToggleTools?: () => void;
}

const Actions = React.memo(
  ({
    status,
    serverName,
    onDisconnect,
    onManage,
    onAuthenticate,
    onReconnect,
    onDelete,
    toolCount,
    isToolsExpanded,
    onToggleTools,
  }) => {
    const { isHovered: isParentHovered } = useActionCardContext();
    const showViewToolsButton =
      (status === ActionStatus.CONNECTED ||
        status === ActionStatus.FETCHING ||
        status === ActionStatus.DISCONNECTED) &&
      !isToolsExpanded &&
      onToggleTools;

    // Connected state
    if (status === ActionStatus.CONNECTED || status === ActionStatus.FETCHING) {
      return (
        <div className="flex flex-col gap-1 items-end">
          <div className="flex items-center">
            {onDisconnect && (
              <div
                className={cn(
                  "inline-flex transition-all duration-200 ease-out",
                  isParentHovered
                    ? "opacity-100 translate-x-0 pointer-events-auto"
                    : "opacity-0 translate-x-2 pointer-events-none"
                )}
              >
                <IconButton
                  icon={SvgUnplug}
                  tooltip="Disconnect Server"
                  tertiary
                  onClick={onDisconnect}
                  aria-label={`Disconnect ${serverName} server`}
                />
              </div>
            )}
            {onManage && (
              <IconButton
                icon={SvgSettings}
                tooltip="Manage Server"
                tertiary
                onClick={onManage}
                aria-label={`Manage ${serverName} server`}
              />
            )}
          </div>
          {showViewToolsButton && (
            <Button
              tertiary
              onClick={onToggleTools}
              rightIcon={SvgChevronDown}
              aria-label={`View tools for ${serverName}`}
            >
              {status === ActionStatus.FETCHING
                ? "Fetching tools..."
                : `View ${toolCount ?? 0} tool${toolCount !== 1 ? "s" : ""}`}
            </Button>
          )}
        </div>
      );
    }

    // Pending state
    if (status === ActionStatus.PENDING) {
      return (
        <div className="flex flex-col gap-1 items-end shrink-0">
          {onAuthenticate && (
            <Button
              tertiary
              onClick={onAuthenticate}
              rightIcon={SvgArrowExchange}
              aria-label={`Authenticate and connect to ${serverName}`}
            >
              Authenticate
            </Button>
          )}
          <div
            className={cn(
              "flex gap-1 items-center transition-opacity duration-200 ease-out",
              isParentHovered
                ? "opacity-100 pointer-events-auto"
                : "opacity-0 pointer-events-none"
            )}
          >
            {onDelete && (
              <IconButton
                icon={SvgTrash}
                tooltip="Delete Server"
                tertiary
                onClick={onDelete}
                aria-label={`Delete ${serverName} server`}
              />
            )}
            {onManage && (
              <IconButton
                icon={SvgSettings}
                tooltip="Manage Server"
                tertiary
                onClick={onManage}
                aria-label={`Manage ${serverName} server`}
              />
            )}
          </div>
        </div>
      );
    }

    // Disconnected state
    return (
      <div className="flex flex-col gap-1 items-end shrink-0">
        <div className="flex gap-1 items-end">
          {onReconnect && (
            <Button
              secondary
              onClick={onReconnect}
              rightIcon={SvgPlug}
              aria-label={`Reconnect to ${serverName}`}
            >
              Reconnect
            </Button>
          )}
          {onManage && (
            <IconButton
              icon={SvgSettings}
              tooltip="Manage Server"
              tertiary
              onClick={onManage}
              aria-label={`Manage ${serverName} server`}
            />
          )}
        </div>
        {showViewToolsButton && (
          <Button
            tertiary
            onClick={onToggleTools}
            rightIcon={SvgChevronDown}
            aria-label={`View tools for ${serverName}`}
            disabled
          >
            {`View ${toolCount ?? 0} tool${toolCount !== 1 ? "s" : ""}`}
          </Button>
        )}
      </div>
    );
  }
);
Actions.displayName = "Actions";

export default Actions;
