"use client";
import { ActionStatus } from "@/lib/tools/interfaces";
import React from "react";
import { Button } from "@opal/components";
import {
  SvgArrowExchange,
  SvgChevronDown,
  SvgPlug,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { useActionCardContext } from "@/sections/actions/ActionCardContext";
import { cn } from "@opal/utils";

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
  }: ActionsProps) => {
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
                <Button
                  icon={SvgUnplug}
                  tooltip="断开服务器"
                  prominence="tertiary"
                  onClick={onDisconnect}
                  aria-label={`断开 ${serverName} 服务器`}
                />
              </div>
            )}
            {onManage && (
              <Button
                icon={SvgSettings}
                tooltip="管理服务器"
                prominence="tertiary"
                onClick={onManage}
                aria-label={`管理 ${serverName} 服务器`}
              />
            )}
          </div>
          {showViewToolsButton && (
            <Button
              prominence="tertiary"
              onClick={onToggleTools}
              rightIcon={SvgChevronDown}
              aria-label={`查看 ${serverName} 的工具`}
            >
              {status === ActionStatus.FETCHING
                ? "正在获取工具..."
                : `查看 ${toolCount ?? 0} 个工具`}
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
              prominence="tertiary"
              onClick={onAuthenticate}
              rightIcon={SvgArrowExchange}
              aria-label={`认证并连接到 ${serverName}`}
            >
              认证
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
              <Button
                icon={SvgTrash}
                tooltip="删除服务器"
                prominence="tertiary"
                onClick={onDelete}
                aria-label={`删除 ${serverName} 服务器`}
              />
            )}
            {onManage && (
              <Button
                icon={SvgSettings}
                tooltip="管理服务器"
                prominence="tertiary"
                onClick={onManage}
                aria-label={`管理 ${serverName} 服务器`}
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
              prominence="secondary"
              onClick={onReconnect}
              rightIcon={SvgPlug}
              aria-label={`重新连接到 ${serverName}`}
            >
              重新连接
            </Button>
          )}
          {onManage && (
            <Button
              icon={SvgSettings}
              tooltip="管理服务器"
              prominence="tertiary"
              onClick={onManage}
              aria-label={`管理 ${serverName} 服务器`}
            />
          )}
        </div>
        {showViewToolsButton && (
          <Button
            disabled
            prominence="tertiary"
            onClick={onToggleTools}
            rightIcon={SvgChevronDown}
            aria-label={`查看 ${serverName} 的工具`}
          >
            {`查看 ${toolCount ?? 0} 个工具`}
          </Button>
        )}
      </div>
    );
  }
);
Actions.displayName = "Actions";

export default Actions;
