"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgArrowExchange } from "@opal/icons";
import { Content } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";

export interface StaticPermissionLabelProps {
  icon: IconFunctionComponent;
  label: string;
  muted?: boolean;
}

// Non-interactive permission display sitting in the row's permission column.
export function StaticPermissionLabel({
  icon,
  label,
  muted = false,
}: StaticPermissionLabelProps) {
  return (
    <Content
      font="main-ui-action"
      titleColor={muted ? "text-03" : undefined}
      icon={icon}
      title={label}
    />
  );
}

export interface TransferTrailingButtonProps {
  onTransfer: () => void;
}

export function TransferTrailingButton({
  onTransfer,
}: TransferTrailingButtonProps) {
  const t = useTranslations("chat.modals.share");

  return (
    <Button
      icon={SvgArrowExchange}
      onClick={onTransfer}
      prominence="tertiary"
      size="sm"
      tooltip={t("transferOwnership.trailingButton.tooltip")}
    />
  );
}
