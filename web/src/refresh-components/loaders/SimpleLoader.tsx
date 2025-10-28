import { SvgProps } from "@/icons";
import SvgLoader from "@/icons/loader";
import { cn } from "@/lib/utils";

export default function SimpleLoader({ className }: SvgProps) {
  return (
    <SvgLoader
      className={cn("h-[1rem] w-[1rem] stroke-text-03 animate-spin", className)}
    />
  );
}
