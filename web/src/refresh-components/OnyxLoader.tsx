import React from "react";
import { cn } from "@opal/utils";
import { Text } from "@opal/components";
import SvgOnyxOctagon from "@opal/icons/onyx-octagon";
import SvgOnyxLogo from "@opal/icons/onyx-logo";
import "./onyx-loader.css";

interface OnyxLoaderProps {
  /** Size of the animated mark, in pixels. Default: 64 (matches the design). */
  size?: number;
  /**
   * Label rendered below the mark. Defaults to "Loading …".
   * Pass `null` to render the mark on its own.
   */
  text?: string | null;
  className?: string;
}

/**
 * Onyx-branded loading indicator.
 *
 * Renders the Onyx mark rotating a full turn while crossfading between the
 * octagon outline and the diamond logo (2s loop), per the Onyx UI Library
 * design. Both layers use `currentColor`, so the loader adapts to the
 * surrounding theme via `colors.css`.
 */
export function OnyxLoader({
  size = 64,
  text = "Loading …",
  className,
}: OnyxLoaderProps) {
  return (
    <div
      role="status"
      aria-label={text ?? "Loading"}
      className={cn(
        "flex w-full flex-col items-center justify-center gap-3 p-5 my-auto text-text-03",
        className
      )}
    >
      <div className="relative shrink-0" style={{ width: size, height: size }}>
        <div className="onyx-loader__rotator">
          <SvgOnyxOctagon
            size={size}
            className="onyx-loader__layer onyx-loader__outline"
          />
          <SvgOnyxLogo
            size={size}
            className="onyx-loader__layer onyx-loader__mark"
          />
        </div>
      </div>
      {text !== null && (
        <Text font="main-ui-muted" color="text-03">
          {text}
        </Text>
      )}
    </div>
  );
}

export default OnyxLoader;
