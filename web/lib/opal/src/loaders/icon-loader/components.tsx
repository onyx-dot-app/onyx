"use client";

import { SvgSimpleLoader } from "@opal/icons";
import { useOpalStrings } from "@opal/strings";
import { cn } from "@opal/utils";
import {
  LOADER_COLOR_CLASS,
  type LoaderColor,
} from "@opal/components/loader/components";

interface IconLoaderProps {
  /** Size of the spinner, in pixels. @default 16 */
  size?: number;

  /** Spinner color token. `"inherit"` follows the surrounding text color. @default "inherit" */
  color?: LoaderColor;
}

/**
 * The inline spinner: `SvgSimpleLoader` at a set size. The icon itself is
 * unsized; this is where the size is decided. Holds still under
 * `prefers-reduced-motion`.
 */
function IconLoader({ size = 16, color = "inherit" }: IconLoaderProps) {
  const strings = useOpalStrings();
  return (
    <SvgSimpleLoader
      size={size}
      role="status"
      aria-label={strings.loading}
      className={cn(
        "shrink-0 motion-reduce:animate-none",
        LOADER_COLOR_CLASS[color]
      )}
    />
  );
}

export { IconLoader, type IconLoaderProps };
