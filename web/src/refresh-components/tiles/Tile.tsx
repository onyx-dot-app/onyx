import type { FunctionComponent } from "react";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { Interactive } from "@opal/core";
import { SvgExternalLink, SvgFileText, SvgX } from "@opal/icons";
import type { IconProps } from "@opal/types";
import IconButton from "../buttons/IconButton";
import { ExternalLink } from "lucide-react";
import Truncated from "../texts/Truncated";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TileFileState = "default" | "processing" | "disabled";

interface TileFileProps {
  type: "file";
  title?: string;
  description?: string;
  icon?: FunctionComponent<IconProps>;
  onRemove?: () => void;
  onOpen?: () => void;
  state?: TileFileState;
}

interface TileButtonProps {
  type: "button";
  title?: string;
  description?: string;
  icon?: FunctionComponent<IconProps>;
  onClick?: () => void;
  disabled?: boolean;
}

type TileProps = TileFileProps | TileButtonProps;

// ---------------------------------------------------------------------------
// Tile
// ---------------------------------------------------------------------------

export default function Tile(props: TileProps) {
  if (props.type === "file") {
    return <FileTile {...props} />;
  }
  return <ButtonTile {...props} />;
}

// ---------------------------------------------------------------------------
// File variant
// ---------------------------------------------------------------------------

function FileTile({
  title,
  description,
  icon,
  onRemove,
  onOpen,
  state = "default",
}: TileFileProps) {
  const Icon = icon ?? SvgFileText;
  const isMuted = state === "processing" || state === "disabled";

  return (
    <div className="group/Tile">
      <div
        className={cn(
          "relative min-w-[7.5rem] max-w-[15rem]",
          "border rounded-12 p-1",
          "flex flex-row items-center",
          "transition-colors duration-150",
          // Outer container bg + border per state
          isMuted
            ? "bg-background-neutral-02 border-border-01"
            : "bg-background-tint-00 border-border-01",
          // Hover overrides (disabled gets none)
          state !== "disabled" && "group-hover/Tile:border-border-02",
          state === "default" && "group-hover/Tile:bg-background-tint-02"
        )}
      >
        {onRemove && (
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
        )}

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
          <div className="min-w-0 flex pl-1">
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
                  <Truncated
                    secondaryBody
                    text02
                    className={cn(
                      state === "processing" && "group-hover/Tile:text-text-03"
                    )}
                  >
                    {description}
                  </Truncated>
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
                  <Truncated secondaryBody text03>
                    {description}
                  </Truncated>
                )}
              </div>
            )}
            {onOpen && (
              <div className="h-full">
                <IconButton internal icon={ExternalLink} />
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Button variant
// ---------------------------------------------------------------------------

function ButtonTile({
  title,
  description,
  icon,
  onClick,
  disabled,
}: TileButtonProps) {
  const Icon = icon;

  return (
    <Interactive.Base
      variant="default"
      subvariant="secondary"
      group="group/Tile"
      onClick={onClick}
      disabled={disabled}
    >
      <div className={cn("rounded-08 p-1.5", "flex flex-row gap-2")}>
        {(title || description) && (
          <div className="min-w-0 flex flex-col px-0.5">
            {title && (
              <Text
                secondaryAction
                text02={disabled}
                text04={!disabled}
                className="truncate"
              >
                {title}
              </Text>
            )}
            {description && (
              <Text secondaryBody text02={disabled} text03={!disabled}>
                {description}
              </Text>
            )}
          </div>
        )}

        {Icon && (
          <div className="flex items-start justify-center">
            <Icon
              size={16}
              className={cn(
                disabled
                  ? "stroke-text-01"
                  : "stroke-text-03 group-hover/Tile:stroke-text-04"
              )}
            />
          </div>
        )}
      </div>
    </Interactive.Base>
  );
}
