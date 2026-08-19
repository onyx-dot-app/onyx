// Vendored RNR `separator`, reconciled to Onyx tokens (`bg-border` → `bg-border-01`).
import { cn } from "@/lib/utils";
import * as SeparatorPrimitive from "@rn-primitives/separator";

function Separator({
  className,
  orientation = "horizontal",
  decorative = true,
  ...props
}: React.ComponentProps<typeof SeparatorPrimitive.Root>) {
  return (
    <SeparatorPrimitive.Root
      decorative={decorative}
      orientation={orientation}
      className={cn(
        "shrink-0 bg-border-01",
        orientation === "horizontal" ? "h-[1px] w-full" : "h-full w-[1px]",
        className,
      )}
      {...props}
    />
  );
}

export { Separator };
