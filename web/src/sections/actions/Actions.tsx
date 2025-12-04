"use client";
import { ActionStatus } from "@/lib/tools/types";
import React from "react";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgUnplug from "@/icons/unplug";
import SvgSettings from "@/icons/settings";
import SvgTrash from "@/icons/trash";
import Button from "@/refresh-components/buttons/Button";
import SvgPlug from "@/icons/plug";
import SvgArrowExchange from "@/icons/arrow-exchange";
import SvgChevronDown from "@/icons/chevron-down";

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

const Actions: React.FC<ActionsProps> = React.memo(
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
              <IconButton
                icon={SvgUnplug}
                tooltip="Disconnect Server"
                tertiary
                onClick={onDisconnect}
                aria-label={`Disconnect ${serverName} server`}
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
        <div className="flex flex-col gap-1 items-end p-1 shrink-0">
          {onAuthenticate && (
            <Button
              secondary
              onClick={onAuthenticate}
              rightIcon={SvgArrowExchange}
              aria-label={`Authenticate and connect to ${serverName}`}
            >
              Authenticate
            </Button>
          )}
          <div className="flex gap-1 items-center">
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
