"use client";

import type { IconFunctionComponent } from "@opal/types";
import { Button, SelectCard } from "@opal/components";
import { Content, Card } from "@opal/layouts";
import {
  SvgArrowExchange,
  SvgArrowRightCircle,
  SvgCheckSquare,
  SvgSettings,
  SvgUnplug,
} from "@opal/icons";

/**
 * ProviderCard — a stateful card for selecting / connecting / disconnecting
 * an external service provider (LLM, search engine, voice model, etc.).
 *
 * Built on opal `SelectCard` + `Card.Header`. Maps a three-state
 * status model to the `SelectCard` state system:
 *
 * | Status         | SelectCard state | Right action           |
 * |----------------|------------------|------------------------|
 * | `disconnected` | `empty`          | "Connect" button       |
 * | `connected`    | `filled`         | "Set as Default" button|
 * | `selected`     | `selected`       | "Current Default" label|
 *
 * Bottom-right actions (Disconnect, Edit) are always visible when the
 * provider is connected or selected.
 *
 * Used on admin configuration pages: Web Search, Image Generation,
 * Voice, and LLM Configuration.
 *
 * @example
 * ```tsx
 * <ProviderCard
 *   icon={SvgGlobe}
 *   title="Exa"
 *   description="Exa.ai"
 *   status="connected"
 *   onConnect={() => openModal()}
 *   onSelect={() => setDefault(id)}
 *   onEdit={() => openEditModal()}
 *   onDisconnect={() => confirmDisconnect(id)}
 * />
 * ```
 */

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
      state={STATUS_TO_STATE[status]}
      padding="sm"
      rounding="lg"
      aria-label={ariaLabel}
      onClick={isDisconnected && onConnect ? onConnect : undefined}
    >
      <Card.Header
        headerChildren={
          <Content
            sizePreset="main-ui"
            variant="section"
            icon={icon}
            title={title}
            description={description}
          />
        }
        topRightChildren={
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
