import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import { SvgLoader } from "@opal/icons";

export default function SimpleLoader({ className, ...props }: IconProps) {
  return (
    <SvgLoader className={cn("h-4 w-4 animate-spin", className)} {...props} />
  );
}
