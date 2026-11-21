"use client";

import type { IconFunctionComponent } from "@opal/types";
import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { ContentAction, ReverseContent, Section } from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { IconLoader } from "@opal/loaders";
import {
  SvgArrowExchange,
  SvgCheckCircle,
  SvgRefreshCw,
  SvgSettings,
  SvgTrash,
  SvgUnplug,
} from "@opal/icons";

/**
 * Where an integration is in its lifecycle:
 *
 * ```
 * [not_set_up] <---------------------- (delete)
 *      |                                  |
 *      | (connect)                        |
 *      v                                  |
 * [connected] <-- (disconnect / reconnect) --> [disconnected]
 * ```
 *
 * A disconnected integration keeps its settings, so it reconnects without
 * setup. Only delete removes them.
 */
type IntegrationState = "not_set_up" | "connected" | "disconnected";

interface IntegrationCardProps {
  icon: IconFunctionComponent;
  title: string;
  description: string;
  state: IntegrationState;
  /** Not set up: the card click and its Connect button. */
  onConnect?: () => void;
  /**
   * Opens the settings: the card click when connected, and an Edit button on
   * hover when connected or disconnected.
   */
  onConfigure?: () => void;
  /** Connected: a Disconnect button on hover. */
  onDisconnect?: () => void;
  /** Disconnected: the card click and its Reconnect button. */
  onReconnect?: () => void;
  /** Disconnected: a Delete button on hover. */
  onDelete?: () => void;
  /**
   * Connected: a Refresh button, and the card click when there is no
   * `onConfigure`.
   */
  onRefresh?: () => void;
  /** Connected: the corner status. Defaults to a "Connected" check. */
  status?: React.ReactNode;
  /** Connected but failing: the card looks empty and its title is struck. */
  broken?: boolean;
  /**
   * An action is running or the status loads: the buttons are disabled. A
   * disconnected card shows `status` in place of Reconnect, with the
   * Disconnect and Refresh buttons of a connected card.
   */
  busy?: boolean;
  /** Refresh is running: its button spins. */
  refreshing?: boolean;
  /** The card click does nothing, e.g. while the status loads. */
  clickDisabled?: boolean;
  /** Keeps the hover buttons shown, e.g. while one of its modals is open. */
  holdHover?: boolean;
  "aria-label"?: string;
}

/**
 * The card of an integration that is connected, disconnected or not set up
 * (Tracing, Code Interpreter). Each state has its own card click, so the card
 * never shows a hover that does nothing.
 */
function IntegrationCard({
  icon,
  title,
  description,
  state,
  onConnect,
  onConfigure,
  onDisconnect,
  onReconnect,
  onDelete,
  onRefresh,
  status,
  broken = false,
  busy = false,
  refreshing = false,
  clickDisabled = false,
  holdHover = false,
  "aria-label": ariaLabel,
}: IntegrationCardProps) {
  const t = useTranslations("admin.shared.integrationCard");

  const onClick =
    state === "not_set_up"
      ? onConnect
      : state === "connected"
        ? (onConfigure ?? onRefresh)
        : onReconnect;

  const connectedStatus = status ?? (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      padding={2}
    >
      <ReverseContent
        font="main-ui-body"
        icon={SvgCheckCircle}
        title={t("connected.label")}
        color="success"
        titleColor="text-03"
      />
    </Section>
  );

  function hoverButton(
    icon: IconFunctionComponent,
    tooltip: string,
    label: string,
    action: () => void
  ) {
    return (
      <Hoverable.Item group="IntegrationCard" variant="appear-on-hover">
        <Button
          icon={icon}
          tooltip={tooltip}
          aria-label={label}
          prominence="tertiary"
          size="md"
          disabled={busy}
          onClick={(event) => {
            event.stopPropagation();
            action();
          }}
        />
      </Hoverable.Item>
    );
  }

  // A disconnected card that is reconnecting shows a connected card's buttons.
  const showsConnectedActions =
    state === "connected" || (state === "disconnected" && busy);

  const actions = (
    <div className="px-1 pb-1">
      <Section flexDirection="row" justifyContent="end" gap={1}>
        {showsConnectedActions &&
          onDisconnect &&
          hoverButton(
            SvgUnplug,
            t("disconnectButton.tooltip"),
            t("disconnectButton.ariaLabel", { title }),
            onDisconnect
          )}
        {state === "disconnected" &&
          !busy &&
          onDelete &&
          hoverButton(
            SvgTrash,
            t("deleteButton.tooltip"),
            t("deleteButton.ariaLabel", { title }),
            onDelete
          )}
        {state !== "not_set_up" &&
          onConfigure &&
          hoverButton(
            SvgSettings,
            t("editButton.tooltip"),
            t("editButton.ariaLabel", { title }),
            onConfigure
          )}
        {showsConnectedActions && onRefresh && (
          <Button
            icon={refreshing ? IconLoader : SvgRefreshCw}
            tooltip={t("refreshButton.tooltip")}
            prominence="tertiary"
            size="md"
            disabled={busy}
            onClick={(event) => {
              event.stopPropagation();
              onRefresh();
            }}
          />
        )}
      </Section>
    </div>
  );

  const primaryButton = (label: string, action: () => void) => (
    <Button
      prominence="tertiary"
      rightIcon={SvgArrowExchange}
      onClick={(event) => {
        event.stopPropagation();
        action();
      }}
    >
      {label}
    </Button>
  );

  return (
    <Hoverable.Root
      group="IntegrationCard"
      interaction={holdHover ? "hover" : "rest"}
    >
      <SelectCard
        state={state === "connected" && !broken ? "filled" : "empty"}
        padding={2}
        rounding={4}
        aria-label={ariaLabel ?? title}
        onClick={clickDisabled ? undefined : onClick}
      >
        <ContentAction
          font="main-ui-action"
          icon={icon}
          title={title}
          suffix={
            state === "disconnected" ? t("disconnected.suffix") : undefined
          }
          strikethrough={state === "connected" && broken}
          description={description}
          padding={2}
          rightChildren={
            <Section alignItems="end" justifyContent="start" gap={0}>
              {state === "not_set_up"
                ? onConnect &&
                  primaryButton(t("connectButton.label"), onConnect)
                : state === "connected"
                  ? connectedStatus
                  : busy && status
                    ? status
                    : onReconnect &&
                      primaryButton(t("reconnectButton.label"), onReconnect)}
              {state !== "not_set_up" &&
                (showsConnectedActions
                  ? onDisconnect || onRefresh || onConfigure
                  : onDelete || onConfigure) &&
                actions}
            </Section>
          }
        />
      </SelectCard>
    </Hoverable.Root>
  );
}

export { IntegrationCard, type IntegrationCardProps, type IntegrationState };
