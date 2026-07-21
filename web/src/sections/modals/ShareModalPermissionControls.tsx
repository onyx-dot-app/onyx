"use client";

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
      color={muted ? "muted" : undefined}
      icon={icon}
      sizePreset="main-ui"
      title={label}
      variant="section"
    />
  );
}

export interface TransferTrailingButtonProps {
  onTransfer: () => void;
}

export function TransferTrailingButton({
  onTransfer,
}: TransferTrailingButtonProps) {
  return (
    <Button
      icon={SvgArrowExchange}
      onClick={onTransfer}
      prominence="tertiary"
      size="sm"
      tooltip="Transfer Ownership"
    />
  );
}
