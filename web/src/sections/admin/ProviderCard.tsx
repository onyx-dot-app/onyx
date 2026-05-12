"use client";

import type { IconFunctionComponent } from "@opal/types";
import { Button, SelectCard } from "@opal/components";
import { Content, ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { Hoverable } from "@opal/core";
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
 * Built on opal `SelectCard` + `ContentAction`. Maps a three-state
 * status model to the `SelectCard` state system:
 *
 * | Status         | SelectCard state | Right action           |
 * |----------------|------------------|------------------------|
 * | `disconnected` | `empty`          | "Connect" button       |
 * | `connected`    | `filled`         | "Set as Default" button|
 * | `selected`     | `selected`       | "Current Default" label|
 *
 * Disconnect and Edit buttons are shown on hover when the provider
 * is connected or selected.
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
 *   onDeselect={() => removeDefault(id)}
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
  /** When true, keeps the disconnect button visible (as if hovered). */
  disconnectModalOpen?: boolean;
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
  disconnectModalOpen,
  selectedLabel = "Current Default",
  "aria-label": ariaLabel,
}: ProviderCardProps) {
  const isDisconnected = status === "disconnected";
  const isConnected = status === "connected";
  const isSelected = status === "selected";

  return (
    <Hoverable.Root
      group="ProviderCard"
      interaction={disconnectModalOpen ? "hover" : "rest"}
    >
      <SelectCard
        state={STATUS_TO_STATE[status]}
        padding="sm"
        rounding="lg"
        aria-label={ariaLabel}
        onClick={
          isDisconnected && onConnect
            ? onConnect
            : isConnected && onSelect
              ? onSelect
              : isSelected && onDeselect
                ? onDeselect
                : undefined
        }
      >
        <ContentAction
          sizePreset="main-ui"
          variant="section"
          icon={icon}
          title={title}
          description={description}
          padding="lg"
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
            ) : (
              <Section alignItems="end" justifyContent="start" gap={0}>
                {isConnected && onSelect ? (
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
                ) : undefined}
                {(onDisconnect || onEdit) && (
                  <div className="px-1 pb-1">
                    <Section
                      flexDirection="row"
                      justifyContent="end"
                      gap={0.25}
                    >
                      {onDisconnect && (
                        <Hoverable.Item
                          group="ProviderCard"
                          variant="appear-on-hover"
                        >
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
                        </Hoverable.Item>
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
                    </Section>
                  </div>
                )}
              </Section>
            )
          }
        />
      </SelectCard>
    </Hoverable.Root>
  );
}

export type { ProviderCardProps, ProviderStatus };
