import type { FunctionComponent } from "react";

import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import { Interactive } from "@opal/core";
import type { IconProps } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ButtonTileProps {
  title?: string;
  description?: string;
  icon?: FunctionComponent<IconProps>;
  onClick?: () => void;
  disabled?: boolean;
}

// ---------------------------------------------------------------------------
// ButtonTile
// ---------------------------------------------------------------------------

export default function ButtonTile({
  title,
  description,
  icon,
  onClick,
  disabled,
}: ButtonTileProps) {
  const Icon = icon;

  return (
    <Interactive.Base
      variant="default"
      prominence="secondary"
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
