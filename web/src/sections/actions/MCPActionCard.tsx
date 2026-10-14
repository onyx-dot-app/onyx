"use client";

import React from "react";
import { useTranslations } from "next-intl";
import ActionCard from "@/sections/actions/ActionCard";
import { Text } from "@opal/components";
import { ActionStatus } from "@/lib/tools/types";
import type { IconProps } from "@opal/types";
import { SvgServer } from "@opal/icons";
import { cn } from "@opal/utils";

export interface MCPActionCardProps {
  title: string;
  description: string;
  logo?: React.FunctionComponent<IconProps>;
  status: ActionStatus;
  toolCount?: number;
  onOpen?: () => void;
  className?: string;
}

export default function MCPActionCard({
  title,
  description,
  logo,
  status,
  toolCount = 0,
  onOpen,
  className,
}: MCPActionCardProps) {
  const t = useTranslations("actions");
  const statusLabel =
    status === ActionStatus.CONNECTED
      ? t("mcpCard.status.ready", { count: toolCount })
      : status === ActionStatus.FETCHING
        ? t("mcpCard.status.loading")
        : status === ActionStatus.DISCONNECTED
          ? t("mcpCard.status.disconnected")
          : t("mcpCard.status.incomplete");

  return (
    <ActionCard
      title={title}
      description={description}
      icon={logo || SvgServer}
      status={status}
      actions={null}
      footer={
        <div className="flex items-center gap-2 px-3 pb-3">
          <div
            className={cn(
              "flex shrink-0 justify-center",
              status === ActionStatus.CONNECTED ? "w-7" : "w-5"
            )}
          >
            <span
              aria-hidden="true"
              className={cn(
                "size-2 shrink-0 rounded-full",
                status === ActionStatus.CONNECTED
                  ? "bg-status-success-05"
                  : status === ActionStatus.DISCONNECTED
                    ? "bg-status-error-05"
                    : "bg-status-warning-05"
              )}
            />
          </div>
          <Text font="secondary-body" color="text-03">
            {statusLabel}
          </Text>
        </div>
      }
      onActivate={onOpen}
      className={className}
      ariaLabel={t("mcpCard.card.ariaLabel", { title })}
    />
  );
}
