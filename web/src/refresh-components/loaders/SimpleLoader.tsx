import type { IconProps } from "@opal";
import { cn } from "@/lib/utils";
import { SvgLoader } from "@opal/icons";

export default function SimpleLoader({ className }: IconProps) {
  return (
    <SvgLoader
      className={cn("h-[1rem] w-[1rem] stroke-text-03 animate-spin", className)}
    />
  );
}
