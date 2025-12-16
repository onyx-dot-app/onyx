"use client";

import React, { useState } from "react";
import { cn } from "@/lib/utils";
import { ActionStatus } from "@/lib/tools/types";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import type { IconProps } from "@opal";
import Truncated from "@/refresh-components/texts/Truncated";
import { SvgEdit } from "@opal/icons";

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
  const [isHovered, setIsHovered] = useState(false);

  const isConnected = status === ActionStatus.CONNECTED;
  const isPending = status === ActionStatus.PENDING;
  const isDisconnected = status === ActionStatus.DISCONNECTED;
  const isFetching = status === ActionStatus.FETCHING;

  const showEditButton = isPending;
  const showRenameIcon =
    onRename && isHovered && !isRenaming && (isConnected || isFetching);

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
    <div
      className="flex flex-1 gap-2 items-start max-w-[480px]"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div
        className={cn(
          "flex items-center px-0 py-0.5 shrink-0",
          isConnected && "h-7 w-7 justify-center p-1"
        )}
      >
        <Icon size={20} className="h-5 w-5 stroke-text-04" />
      </div>

      <div className="flex flex-col items-start flex-1 min-w-0">
        <div className="flex gap-1 items-center w-full">
          {isConnected || isFetching ? (
            <div className="flex items-center gap-1 flex-1 min-w-0">
              {isRenaming ? (
                <ButtonRenaming
                  initialName={title}
                  onRename={handleRename}
                  onClose={() => setIsRenaming(false)}
                  className="text-text-04 font-main-content-emphasis"
                />
              ) : (
                <Truncated mainContentEmphasis text04 className="truncate">
                  {title}
                </Truncated>
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
          ) : isPending ? (
            <>
              <Text headingH3 text04>
                {title}
              </Text>
              <Text mainUiMuted text03>
                (Not Authenticated)
              </Text>
            </>
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

export default ActionCardHeader;
