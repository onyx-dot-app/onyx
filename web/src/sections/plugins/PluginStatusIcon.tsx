import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";

export type PluginIndicatorStatus =
  | "active"
  | "issues"
  | "inactive"
  | "unknown";

const colors: Record<PluginIndicatorStatus, string> = {
  active: "bg-status-success-05",
  issues: "bg-status-warning-05",
  inactive: "bg-text-03",
  unknown: "bg-text-02",
};

export default function PluginStatusIcon({
  primary,
  secondary,
  tertiary,
  className,
}: IconProps & {
  primary: PluginIndicatorStatus;
  secondary?: PluginIndicatorStatus;
  tertiary?: PluginIndicatorStatus;
}) {
  if (secondary && tertiary)
    return (
      <span
        aria-hidden
        className={cn(
          "relative block size-3 overflow-hidden rounded-full",
          className
        )}
      >
        <span
          className={cn(
            "absolute inset-0 [clip-path:polygon(50%_50%,0_79%,0_0,50%_0)]",
            colors[primary]
          )}
        />
        <span
          className={cn(
            "absolute inset-0 [clip-path:polygon(50%_50%,50%_0,100%_0,100%_79%)]",
            colors[secondary]
          )}
        />
        <span
          className={cn(
            "absolute inset-0 [clip-path:polygon(50%_50%,100%_79%,100%_100%,0_100%,0_79%)]",
            colors[tertiary]
          )}
        />
        <span className="absolute start-1/2 top-1/2 h-px w-1/2 origin-left -rotate-90 bg-background-neutral-00" />
        <span className="absolute start-1/2 top-1/2 h-px w-1/2 origin-left rotate-30 bg-background-neutral-00" />
        <span className="absolute start-1/2 top-1/2 h-px w-1/2 origin-left rotate-150 bg-background-neutral-00" />
      </span>
    );
  if (!secondary)
    return (
      <span
        aria-hidden
        className={cn("block size-3 rounded-full", colors[primary], className)}
      />
    );
  return (
    <span
      aria-hidden
      className={cn(
        "relative block size-3 overflow-hidden rounded-full",
        className
      )}
    >
      <span
        className={cn(
          "absolute inset-0 [clip-path:polygon(0_0,100%_0,0_100%)]",
          colors[primary]
        )}
      />
      <span
        className={cn(
          "absolute inset-0 [clip-path:polygon(100%_0,100%_100%,0_100%)]",
          colors[secondary]
        )}
      />
      <span className="absolute inset-x-0 top-1/2 h-px -rotate-45 bg-background-neutral-00" />
    </span>
  );
}
