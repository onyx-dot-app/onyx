import type { IconProps } from "@opal/types";
import { cn } from "@/lib/utils";
import { SvgLoader } from "@opal/icons";

export default function SimpleLoader({ className, ...props }: IconProps) {
  return (
    <SvgLoader
      className={cn("h-[1rem] w-[1rem] animate-spin", className)}
      {...props}
    />
  );
}
