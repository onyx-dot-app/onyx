"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";
import { ActionStatus } from "@/lib/tools/interfaces";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import type { IconProps } from "@opal/types";
import Truncated from "@/refresh-components/texts/Truncated";
import { SvgEdit } from "@opal/icons";
import { useActionCardContext } from "@/sections/actions/ActionCardContext";

interface ActionCardHeaderProps {
  title: string;
  description: string;
  icon: React.FunctionComponent<IconProps>;
  status: ActionStatus;
  onEdit?: () => void;
  onRename?: (newName: string) => Promise<void>;
}

function ActionCardHeader({
  title,
  description,
  icon: Icon,
  status,
  onEdit,
  onRename,
}: ActionCardHeaderProps) {
  const [isRenaming, setIsRenaming] = useState(false);
  const { isHovered } = useActionCardContext();

  const isConnected = status === ActionStatus.CONNECTED;
  const isPending = status === ActionStatus.PENDING;
  const isDisconnected = status === ActionStatus.DISCONNECTED;
  const isFetching = status === ActionStatus.FETCHING;

  const showRenameIcon = onRename && isHovered && !isRenaming;

  const handleRename = async (newName: string) => {
    if (onRename) {
      await onRename(newName);
    }
    setIsRenaming(false);
  };

  const handleRenameClick = () => {
    if (onRename) {
      setIsRenaming(true);
    }
  };

  return (
    <div className="flex gap-2 items-start flex-1 min-w-0 mr-2">
      <div
        className={cn(
          "flex items-center px-0 py-0.5 shrink-0",
          isConnected && "h-7 w-7 justify-center p-1"
        )}
      >
        <Icon size={20} className="h-5 w-5 stroke-text-04" />
      </div>

      <div className="flex flex-col items-start flex-1 min-w-0 overflow-hidden">
        <div className="flex items-center gap-1 min-w-0 w-full">
          {isRenaming ? (
            <ButtonRenaming
              initialName={title}
              onRename={handleRename}
              onClose={() => setIsRenaming(false)}
              className={cn(
                "font-main-content-emphasis",
                isConnected || isFetching
                  ? "text-text-04"
                  : isDisconnected
                    ? "text-text-03"
                    : "text-text-04"
              )}
            />
          ) : (
            <div className="min-w-0 shrink overflow-hidden">
              <Truncated
                mainContentEmphasis
                className={cn(
                  "truncate",
                  isConnected || isFetching
                    ? "text-text-04"
                    : isDisconnected
                      ? "text-text-03 line-through"
                      : "text-text-04"
                )}
              >
                {title}
              </Truncated>
            </div>
          )}
          {isPending && !isRenaming && (
            <Text
              as="p"
              mainUiMuted
              text03
              className="shrink-0 whitespace-nowrap"
            >
              (Not Authenticated)
            </Text>
          )}
          {isDisconnected && !isRenaming && (
            <Text
              as="p"
              mainUiMuted
              text02
              className="shrink-0 whitespace-nowrap"
            >
              (Disconnected)
            </Text>
          )}
          {showRenameIcon && (
            <IconButton
              icon={SvgEdit}
              tooltip="Rename"
              internal
              tertiary
              onClick={handleRenameClick}
              className="h-6 w-6 opacity-70 hover:opacity-100"
              aria-label={`Rename ${title}`}
            />
          )}
        </div>

        {isConnected ? (
          <Text as="p" secondaryBody text03 className="w-full">
            {description}
          </Text>
        ) : (
          <Text as="p" secondaryBody text02 className="w-full">
            {description}
          </Text>
        )}
      </div>
    </div>
  );
}

export default ActionCardHeader;
