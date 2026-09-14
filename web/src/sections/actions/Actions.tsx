"use client";
import { ActionStatus } from "@/lib/tools/types";
import React from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import {
  SvgArrowExchange,
  SvgChevronDown,
  SvgPlug,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";
import { Hoverable } from "@opal/core";

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
    const t = useTranslations("actions");

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
              <Hoverable.Item group="action-card" variant="appear-on-hover">
                <Button
                  icon={SvgUnplug}
                  tooltip={t("actionButtons.disconnectButton.tooltip")}
                  prominence="tertiary"
                  onClick={onDisconnect}
                  aria-label={t("actionButtons.disconnectButton.ariaLabel", {
                    serverName,
                  })}
                />
              </Hoverable.Item>
            )}
            {onManage && (
              <Button
                icon={SvgSettings}
                tooltip={t("actionButtons.manageButton.tooltip")}
                prominence="tertiary"
                onClick={onManage}
                aria-label={t("actionButtons.manageButton.ariaLabel", {
                  serverName,
                })}
              />
            )}
          </div>
          {showViewToolsButton && (
            <Button
              prominence="tertiary"
              onClick={onToggleTools}
              rightIcon={SvgChevronDown}
              aria-label={t("actionButtons.viewToolsButton.ariaLabel", {
                serverName,
              })}
            >
              {status === ActionStatus.FETCHING
                ? t("actionButtons.fetchingTools.label")
                : t("actionButtons.viewToolsButton.label", {
                    count: toolCount ?? 0,
                  })}
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
              aria-label={t("actionButtons.authenticateButton.ariaLabel", {
                serverName,
              })}
            >
              {t("actionButtons.authenticateButton.label")}
            </Button>
          )}
          <Hoverable.Item group="action-card" variant="appear-on-hover">
            <div className="flex gap-1 items-center">
              {onDelete && (
                <Button
                  icon={SvgTrash}
                  tooltip={t("actionButtons.deleteButton.tooltip")}
                  prominence="tertiary"
                  onClick={onDelete}
                  aria-label={t("actionButtons.deleteButton.ariaLabel", {
                    serverName,
                  })}
                />
              )}
              {onManage && (
                <Button
                  icon={SvgSettings}
                  tooltip={t("actionButtons.manageButton.tooltip")}
                  prominence="tertiary"
                  onClick={onManage}
                  aria-label={t("actionButtons.manageButton.ariaLabel", {
                    serverName,
                  })}
                />
              )}
            </div>
          </Hoverable.Item>
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
              aria-label={t("actionButtons.reconnectButton.ariaLabel", {
                serverName,
              })}
            >
              {t("actionButtons.reconnectButton.label")}
            </Button>
          )}
          {onManage && (
            <Button
              icon={SvgSettings}
              tooltip={t("actionButtons.manageButton.tooltip")}
              prominence="tertiary"
              onClick={onManage}
              aria-label={t("actionButtons.manageButton.ariaLabel", {
                serverName,
              })}
            />
          )}
        </div>
        {showViewToolsButton && (
          <Button
            disabled
            prominence="tertiary"
            onClick={onToggleTools}
            rightIcon={SvgChevronDown}
            aria-label={t("actionButtons.viewToolsButton.ariaLabel", {
              serverName,
            })}
          >
            {t("actionButtons.viewToolsButton.label", {
              count: toolCount ?? 0,
            })}
          </Button>
        )}
      </div>
    );
  }
);
Actions.displayName = "Actions";

export default Actions;
