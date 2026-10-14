"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { cn } from "@opal/utils";
import { ActionStatus } from "@/lib/tools/types";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import type { IconProps, RichStr } from "@opal/types";
import Truncated from "@/refresh-components/texts/Truncated";
import { SvgEdit } from "@opal/icons";
import { Hoverable } from "@opal/core";

interface ActionCardHeaderProps {
  title: string;
  description: string;
  icon: React.FunctionComponent<IconProps>;
  status: ActionStatus;
  showStatus?: boolean;
  pendingDescription?: string | RichStr;
  onRename?: (newName: string) => Promise<void>;
}

function ActionCardHeader({
  title,
  description,
  icon: Icon,
  status,
  showStatus = true,
  pendingDescription,
  onRename,
}: ActionCardHeaderProps) {
  const t = useTranslations("actions");
  const [isRenaming, setIsRenaming] = useState(false);

  const isConnected = status === ActionStatus.CONNECTED;
  const isPending = status === ActionStatus.PENDING;
  const isDisconnected = status === ActionStatus.DISCONNECTED;
  const isFetching = status === ActionStatus.FETCHING;

  const showRenameIcon = onRename && !isRenaming;

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
    <div className="flex gap-2 items-start flex-1 min-w-0 me-2">
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
          {showRenameIcon && (
            <Hoverable.Item group="action-card" variant="appear-on-hover">
              <div className="opacity-70 hover:opacity-100">
                <Button
                  icon={SvgEdit}
                  tooltip={t("cardHeader.renameButton.tooltip")}
                  prominence="tertiary"
                  size="sm"
                  onClick={handleRenameClick}
                  aria-label={t("cardHeader.renameButton.ariaLabel", { title })}
                />
              </div>
            </Hoverable.Item>
          )}
        </div>

        {showStatus && isPending && !pendingDescription && !isRenaming && (
          <Text as="p" font="main-ui-muted" color="text-03" maxLines={1}>
            {t("cardHeader.notAuthenticated.label")}
          </Text>
        )}
        {showStatus && isDisconnected && !isRenaming && (
          <Text as="p" font="main-ui-muted" color="text-02" maxLines={1}>
            {t("cardHeader.disconnected.label")}
          </Text>
        )}
        <Text
          as="p"
          font="secondary-body"
          color={isConnected ? "text-03" : "text-02"}
          maxLines={2}
          wordWrap="wrap-anywhere"
        >
          {description}
        </Text>
        {showStatus && isPending && pendingDescription && !isRenaming && (
          <div className="pt-2">
            <Text as="p" font="secondary-body" color="text-03">
              {pendingDescription}
            </Text>
          </div>
        )}
      </div>
    </div>
  );
}

export default ActionCardHeader;
