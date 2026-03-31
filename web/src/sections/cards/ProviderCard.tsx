"use client";

import type { IconFunctionComponent } from "@opal/types";
import { Button, SelectCard } from "@opal/components";
import { Content, CardHeaderLayout } from "@opal/layouts";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgSettings,
  SvgUnplug,
} from "@opal/icons";

type ProviderStatus = "disconnected" | "connected" | "selected";

interface ProviderCardProps {
  icon: IconFunctionComponent;
  title: string;
  description: string;
  status: ProviderStatus;
  onConnect?: () => void;
  onSelect?: () => void;
  onDeselect?: () => void;
  onEdit?: () => void;
  onDisconnect?: () => void;
  selectedLabel?: string;
  "aria-label"?: string;
}

const STATUS_TO_STATE = {
  disconnected: "empty",
  connected: "filled",
  selected: "selected",
} as const;

export default function ProviderCard({
  icon,
  title,
  description,
  status,
  onConnect,
  onSelect,
  onDeselect,
  onEdit,
  onDisconnect,
  selectedLabel = "Current Default",
  "aria-label": ariaLabel,
}: ProviderCardProps) {
  const isDisconnected = status === "disconnected";
  const isConnected = status === "connected";
  const isSelected = status === "selected";

  return (
    <SelectCard
      variant="select-card"
      state={STATUS_TO_STATE[status]}
      sizeVariant="lg"
      aria-label={ariaLabel}
      onClick={isDisconnected && onConnect ? onConnect : undefined}
    >
      <CardHeaderLayout
        sizePreset="main-ui"
        variant="section"
        icon={icon}
        title={title}
        description={description}
        rightChildren={
          isDisconnected && onConnect ? (
            <Button
              prominence="tertiary"
              rightIcon={SvgArrowExchange}
              onClick={(e) => {
                e.stopPropagation();
                onConnect();
              }}
            >
              Connect
            </Button>
          ) : isConnected && onSelect ? (
            <Button
              prominence="tertiary"
              rightIcon={SvgArrowRightCircle}
              onClick={(e) => {
                e.stopPropagation();
                onSelect();
              }}
            >
              Set as Default
            </Button>
          ) : isSelected ? (
            <div className="p-2">
              <Content
                title={selectedLabel}
                sizePreset="main-ui"
                variant="section"
                icon={SvgCheckSquare}
              />
            </div>
          ) : undefined
        }
        bottomRightChildren={
          !isDisconnected ? (
            <div className="flex flex-row px-1 pb-1">
              {onDisconnect && (
                <Button
                  icon={SvgUnplug}
                  tooltip="Disconnect"
                  aria-label={`Disconnect ${title}`}
                  prominence="tertiary"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDisconnect();
                  }}
                  size="md"
                />
              )}
              {onEdit && (
                <Button
                  icon={SvgSettings}
                  tooltip="Edit"
                  aria-label={`Edit ${title}`}
                  prominence="tertiary"
                  onClick={(e) => {
                    e.stopPropagation();
                    onEdit();
                  }}
                  size="md"
                />
              )}
            </div>
          ) : undefined
        }
      />
    </SelectCard>
  );
}

export type { ProviderCardProps, ProviderStatus };
