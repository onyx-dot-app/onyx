import type { StandardDiscrimatedSizeVariants } from "@opal/shared";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";

const iconVariants = {
  lg: { padding: "p-0.5", size: 1 },
  md: { padding: "p-0.5", size: 1 },
  sm: { padding: "p-0", size: 1 },
  xs: { padding: "p-0.5", size: 0.75 },
  "2xs": { padding: "p-0", size: 0.75 },
  fit: { padding: "p-0.5", size: 1 },
} as const;

function iconWrapper(
  Icon: IconFunctionComponent | undefined,
  size: StandardDiscrimatedSizeVariants,
  includeSpacer: boolean
) {
  const { padding: p, size: s } = iconVariants[size];

  return Icon ? (
    <div className={cn("interactive-foreground-icon", p)}>
      <Icon
        className="shrink-0"
        style={{
          height: `${s}rem`,
          width: `${s}rem`,
        }}
      />
    </div>
  ) : includeSpacer ? (
    <div />
  ) : null;
}

export { iconWrapper, iconVariants };
