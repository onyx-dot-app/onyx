"use client";

import {
  Button,
  type ButtonProps,
} from "@opal/components/buttons/button/components";
import { SvgPlusCircle } from "@opal/icons";

export type CreateButtonProps = Omit<ButtonProps, "icon">;

/**
 * A thin wrapper over `Button` that fixes `icon={SvgPlusCircle}` on the left
 * and defaults `prominence` to `"secondary"`. All other `Button` props pass
 * through unchanged. Use `Button` directly when you need a different icon.
 */
export default function CreateButton({
  children,
  ...props
}: CreateButtonProps) {
  return (
    <Button icon={SvgPlusCircle} prominence="secondary" {...props}>
      {children ?? "Create"}
    </Button>
  );
}
