"use client";

import type { IconFunctionComponent } from "@opal/types";
import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { ContentAction } from "@opal/layouts";
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
  /** When true, keeps the edit button visible (as if hovered). */
  setupModalOpen?: boolean;
  /** Defaults to the shared "Current Default" label. */
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
  setupModalOpen,
  selectedLabel,
  "aria-label": ariaLabel,
}: ProviderCardProps) {
  const t = useTranslations("admin.shared");
  const resolvedSelectedLabel =
    selectedLabel ?? t("providerCard.currentDefault.label");
  // A name to select the card by — one that says which provider it is rather
  // than what it looks like. Not an accessibility fix: the card is a roleless
  // div with an onClick, so a label alone leaves it pointer-only.
  const label = ariaLabel ?? title;
  const isDisconnected = status === "disconnected";
  const isConnected = status === "connected";
  const isSelected = status === "selected";

  return (
    <Hoverable.Root
      group="ProviderCard"
      interaction={disconnectModalOpen || setupModalOpen ? "hover" : "rest"}
    >
      <SelectCard
        state={STATUS_TO_STATE[status]}
        padding={2}
        rounding={4}
        aria-label={label}
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
          padding={2}
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
                {t("providerCard.connectButton.label")}
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
                    {t("providerCard.setDefaultButton.label")}
                  </Button>
                ) : isSelected ? (
                  <Button
                    variant="action"
                    prominence="tertiary"
                    rightIcon={SvgCheckSquare}
                  >
                    {resolvedSelectedLabel}
                  </Button>
                ) : undefined}
                {(onDisconnect || onEdit) && (
                  <div className="px-1 pb-1">
                    <Section flexDirection="row" justifyContent="end" gap={1}>
                      {onDisconnect && (
                        <Hoverable.Item
                          group="ProviderCard"
                          variant="appear-on-hover"
                        >
                          <Button
                            icon={SvgUnplug}
                            tooltip={t("providerCard.disconnectButton.tooltip")}
                            aria-label={t(
                              "providerCard.disconnectButton.ariaLabel",
                              { title }
                            )}
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
                        <Hoverable.Item
                          group="ProviderCard"
                          variant="appear-on-hover"
                        >
                          <Button
                            icon={SvgSettings}
                            tooltip={t("providerCard.editButton.tooltip")}
                            aria-label={t("providerCard.editButton.ariaLabel", {
                              title,
                            })}
                            prominence="tertiary"
                            onClick={(e) => {
                              e.stopPropagation();
                              onEdit();
                            }}
                            size="md"
                          />
                        </Hoverable.Item>
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
