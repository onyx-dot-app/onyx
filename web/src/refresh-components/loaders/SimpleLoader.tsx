import { SvgLoader, SvgProps } from "@onyx/opal";
import { cn } from "@/lib/utils";

export default function SimpleLoader({ className }: SvgProps) {
  return (
    <SvgLoader
      className={cn("h-[1rem] w-[1rem] stroke-text-03 animate-spin", className)}
    />
  );
}
