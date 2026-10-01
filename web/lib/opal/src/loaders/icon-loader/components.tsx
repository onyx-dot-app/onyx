"use client";

import { SvgLoader } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";

type IconLoaderProps = IconProps;

/**
 * The spinner: the static `SvgLoader` ring, spun, at 16px unless told
 * otherwise. Takes the same props as any icon, so it can be invoked on its
 * own or passed as an `icon` (a Button or Content then sets its own size).
 * Colour follows `currentColor`. Holds still under `prefers-reduced-motion`.
 */
function IconLoader({ size = 16, className, ...props }: IconLoaderProps) {
  const strings = useOpalStrings();
  return (
    <SvgLoader
      size={size}
      role="status"
      aria-label={strings.loading}
      {...props}
      className={cn("shrink-0 motion-safe:animate-spin", className)}
    />
  );
}

export { IconLoader, type IconLoaderProps };
