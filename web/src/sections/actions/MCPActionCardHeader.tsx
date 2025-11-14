"use client";
import { cn } from "@/lib/utils";
import type { MCPActionStatus } from "./types";
import React from "react";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgEdit from "@/icons/edit";

interface MCPActionCardHeaderProps {
  title: string;
  description: string;
  icon: React.ReactNode;
  status: MCPActionStatus;
  onEdit?: () => void;
}

const MCPActionCardHeader: React.FC<MCPActionCardHeaderProps> = React.memo(
  ({ title, description, icon, status, onEdit }) => {
    const isConnected = status === "connected";
    const isPending = status === "pending";
    const isDisconnected = status === "disconnected";

    const showEditButton = isPending;

    return (
      <div className="flex flex-1 gap-2 items-start max-w-[480px] p-2">
        <div
          className={cn(
            "flex items-center px-0 py-0.5 shrink-0",
            isConnected && "h-7 w-7 justify-center p-1"
          )}
        >
          {icon}
        </div>

        <div className="flex flex-col items-start flex-1 min-w-0">
          <div className="flex gap-1 items-center w-full">
            {isConnected ? (
              <Text mainContentEmphasis text04>
                {title}
              </Text>
            ) : isPending ? (
              <Text headingH3 text04>
                {title}
              </Text>
            ) : isDisconnected ? (
              <>
                <Text headingH3 text03 className="line-through">
                  {title}
                </Text>
                <Text mainUiMuted text02>
                  (Disconnected)
                </Text>
              </>
            ) : null}
            {showEditButton && onEdit && (
              <IconButton
                icon={SvgEdit}
                tooltip="Edit"
                internal
                tertiary
                onClick={onEdit}
                className="h-6 w-6"
                aria-label={`Edit ${title}`}
              />
            )}
          </div>

          {isConnected ? (
            <Text secondaryBody text03 className="w-full">
              {description}
            </Text>
          ) : (
            <Text secondaryBody text02 className="w-full">
              {description}
            </Text>
          )}
        </div>
      </div>
    );
  }
);
MCPActionCardHeader.displayName = "MCPActionCardHeader";
export default MCPActionCardHeader;
