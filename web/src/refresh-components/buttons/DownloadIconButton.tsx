"use client";

import { Button, ButtonProps } from "@opal/components";
import { SvgDownload } from "@opal/icons";

/** Omit that distributes over unions, preserving discriminated-union branches. */
type DistributiveOmit<T, K extends PropertyKey> = T extends unknown
  ? Omit<T, K>
  : never;

export type DownloadIconButtonProps = DistributiveOmit<
  ButtonProps,
  "variant" | "icon"
> & {
  onClick: () => void;
};

export default function DownloadIconButton({
  tooltip,
  prominence = "tertiary",
  onClick,
  ...iconButtonProps
}: DownloadIconButtonProps) {
  const buttonProps = {
    prominence,
    ...iconButtonProps,
    icon: SvgDownload,
    onClick,
    tooltip: tooltip || "Download",
  } as ButtonProps;

  return <Button {...buttonProps} />;
}
