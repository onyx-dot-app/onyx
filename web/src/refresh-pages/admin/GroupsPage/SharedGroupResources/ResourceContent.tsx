"use client";

import type { ReactNode } from "react";
import { SvgX } from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { Content } from "@opal/layouts";
import IconButton from "@/refresh-components/buttons/IconButton";

interface ResourceContentProps {
  /** SVG icon for connectors/doc sets. */
  icon?: IconFunctionComponent;
  /** Custom ReactNode icon (e.g. AgentAvatar). Takes priority over `icon`. */
  leftContent?: ReactNode;
  title: string;
  description?: string;
  /** Inline info rendered after description (e.g. source icon stack). */
  infoContent?: ReactNode;
  onRemove: () => void;
}

function ResourceContent({
  icon,
  leftContent,
  title,
  description,
  infoContent,
  onRemove,
}: ResourceContentProps) {
  return (
    <div className="flex flex-1 gap-0.5 items-start p-1.5 rounded-08 bg-background-tint-01 min-w-[240px] max-w-[302px]">
      <div className="flex flex-1 gap-1 p-0.5 items-start min-w-0">
        {leftContent ? (
          <>
            {leftContent}
            <Content
              title={title}
              description={description}
              sizePreset="main-ui"
              variant="section"
            />
          </>
        ) : (
          <Content
            icon={icon}
            title={title}
            description={description}
            sizePreset="main-ui"
            variant="section"
          />
        )}
        {infoContent}
      </div>
      <IconButton small icon={SvgX} onClick={onRemove} className="shrink-0" />
    </div>
  );
}

export default ResourceContent;
