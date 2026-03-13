import React from "react";
import { ContentAction } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type NameCardProps = {
  /** Icon displayed to the left of the title. */
  icon?: IconFunctionComponent;

  /** Custom icon element (takes precedence over `icon`). */
  customIcon?: React.ReactNode;

  /** Primary text. */
  title: string;

  /** Optional secondary text below the title. */
  description?: string;

  /** Content rendered on the right side of the card. */
  rightChildren?: React.ReactNode;
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function NameCard({
  icon,
  customIcon,
  title,
  description,
  rightChildren,
}: NameCardProps) {
  return (
    <div className="bg-background-tint-01 p-2 w-full rounded-08">
      <ContentAction
        icon={customIcon ? () => <>{customIcon}</> : icon}
        title={title}
        description={description}
        sizePreset="main-ui"
        variant="section"
        rightChildren={rightChildren}
        paddingVariant="fit"
      />
    </div>
  );
}
