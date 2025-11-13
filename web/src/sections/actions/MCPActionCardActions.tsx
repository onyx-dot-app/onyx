import { MCPActionStatus } from "./MCPActionCard";
import React from "react";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgUnplug from "@/icons/unplug";
import SvgSettings from "@/icons/settings";
import SvgTrash from "@/icons/trash";
import SvgArrowRight from "@/icons/arrow-right";
import Button from "@/refresh-components/buttons/Button";

interface MCPActionCardActionsProps {
  status: MCPActionStatus;
  serverName: string;
  onDisconnect?: () => void;
  onManage?: () => void;
  onAuthenticate?: () => void;
  onReconnect?: () => void;
  onDelete?: () => void;
}

export const MCPActionCardActions: React.FC<MCPActionCardActionsProps> =
  React.memo(
    ({
      status,
      serverName,
      onDisconnect,
      onManage,
      onAuthenticate,
      onReconnect,
      onDelete,
    }) => {
      // Connected state
      if (status === "connected") {
        return (
          <div className="flex items-center shrink-0">
            {onDisconnect && (
              <IconButton
                icon={SvgUnplug}
                tooltip="Disconnect Server"
                tertiary
                onClick={onDisconnect}
                className="h-9 w-9"
                aria-label={`Disconnect ${serverName} server`}
              />
            )}
            {onManage && (
              <IconButton
                icon={SvgSettings}
                tooltip="Manage Server"
                tertiary
                onClick={onManage}
                className="h-9 w-9"
                aria-label={`Manage ${serverName} server`}
              />
            )}
          </div>
        );
      }

      // Common actions for disconnected and pending states
      const commonActions = (
        <div className="flex gap-1 items-center">
          {onDelete && (
            <IconButton
              icon={SvgTrash}
              tooltip="Delete Server"
              tertiary
              onClick={onDelete}
              className="h-9 w-9"
              aria-label={`Delete ${serverName} server`}
            />
          )}
          {onManage && (
            <IconButton
              icon={SvgSettings}
              tooltip="Manage Server"
              tertiary
              onClick={onManage}
              className="h-9 w-9"
              aria-label={`Manage ${serverName} server`}
            />
          )}
        </div>
      );

      // Pending state
      if (status === "pending") {
        return (
          <div className="flex flex-col gap-1 items-end p-1 shrink-0">
            {onAuthenticate && (
              <Button
                secondary
                onClick={onAuthenticate}
                rightIcon={SvgArrowRight}
                className="bg-background-tint-01 border border-border-01"
                aria-label={`Authenticate and connect to ${serverName}`}
              >
                Authenticate & Connect
              </Button>
            )}
            {commonActions}
          </div>
        );
      }

      // Disconnected state
      return (
        <div className="flex flex-col gap-1 items-end p-1 shrink-0">
          {onReconnect && (
            <Button
              secondary
              onClick={onReconnect}
              rightIcon={SvgArrowRight}
              className="bg-background-tint-01 border border-border-01"
              aria-label={`Reconnect to ${serverName}`}
            >
              Reconnect
            </Button>
          )}
          {commonActions}
        </div>
      );
    }
  );
MCPActionCardActions.displayName = "MCPActionCardActions";
