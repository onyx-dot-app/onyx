import type { FunctionComponent } from "react";

import { cn, noProp } from "@/lib/utils";
import { SvgMaximize2, SvgTextLines, SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";
import IconButton from "../buttons/IconButton";
import Text from "../texts/Text";
import Truncated from "../texts/Truncated";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FileTileState = "default" | "processing" | "disabled";

interface FileTileProps {
  title?: string;
  description?: string;
  icon?: FunctionComponent<IconProps>;
  onRemove?: () => void;
  onOpen?: () => void;
  state?: FileTileState;
}

// ---------------------------------------------------------------------------
// RemoveButton (internal)
// ---------------------------------------------------------------------------

interface RemoveButtonProps {
  onRemove: () => void;
}

function RemoveButton({ onRemove }: RemoveButtonProps) {
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        onRemove();
      }}
      title="Remove"
      aria-label="Remove"
      className={cn(
        "absolute -left-1 -top-1 z-10 h-4 w-4",
        "flex items-center justify-center",
        "rounded-full bg-theme-primary-05 text-text-inverted-05",
        "opacity-0 group-hover/Tile:opacity-100 focus:opacity-100",
        "pointer-events-none group-hover/Tile:pointer-events-auto focus:pointer-events-auto",
        "transition-opacity duration-150"
      )}
    >
      <SvgX size={10} />
    </button>
  );
}

// ---------------------------------------------------------------------------
// FileTile
// ---------------------------------------------------------------------------

export default function FileTile({
  title,
  description,
  icon,
  onRemove,
  onOpen,
  state = "default",
}: FileTileProps) {
  const Icon = icon ?? SvgTextLines;
  const isMuted = state === "processing" || state === "disabled";

  return (
    <div className="group/Tile">
      <div
        onClick={onOpen && state !== "disabled" ? () => onOpen() : undefined}
        className={cn(
          "relative min-w-[7.5rem] max-w-[15rem] h-full",
          "border rounded-12 p-1",
          "flex flex-row items-center",
          "transition-colors duration-150",
          // Outer container bg + border per state
          isMuted
            ? "bg-background-neutral-02 border-border-01"
            : "bg-background-tint-00 border-border-01",
          // Hover overrides (disabled gets none)
          state !== "disabled" && "group-hover/Tile:border-border-02",
          state === "default" && "group-hover/Tile:bg-background-tint-02",
          // Clickable cursor when onOpen is provided and not disabled
          onOpen && state !== "disabled" && "cursor-pointer"
        )}
      >
        {onRemove && <RemoveButton onRemove={onRemove} />}

        <div
          className={cn(
            "shrink-0 h-9 w-9 rounded-08",
            "flex items-center justify-center",
            isMuted ? "bg-background-neutral-03" : "bg-background-tint-01"
          )}
        >
          <Icon
            size={16}
            className={cn(isMuted ? "stroke-text-01" : "stroke-text-02")}
          />
        </div>

        {(title || description || onOpen) && (
          <div className="min-w-0 flex pl-1 w-full justify-between h-full">
            {isMuted ? (
              <div className="flex flex-col min-w-0">
                {title && (
                  <Truncated
                    secondaryAction
                    text02
                    className={cn(
                      "truncate",
                      state === "processing" && "group-hover/Tile:text-text-03"
                    )}
                  >
                    {title}
                  </Truncated>
                )}
                {description && (
                  <Text
                    secondaryBody
                    text02
                    className={cn(
                      "line-clamp-2",
                      state === "processing" && "group-hover/Tile:text-text-03"
                    )}
                  >
                    {description}
                  </Text>
                )}
              </div>
            ) : (
              <div className="flex flex-col min-w-0">
                {title && (
                  <Truncated secondaryAction text04 className="truncate">
                    {title}
                  </Truncated>
                )}
                {description && (
                  <Text secondaryBody text03 className="line-clamp-2">
                    {description}
                  </Text>
                )}
              </div>
            )}
            {onOpen && (
              <div className="h-full">
                <IconButton
                  small
                  icon={SvgMaximize2}
                  onClick={noProp(onOpen)}
                />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
