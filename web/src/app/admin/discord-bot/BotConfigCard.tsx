"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import { Badge } from "@/components/ui/badge";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { ThreeDotsLoader } from "@/components/Loading";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import {
  useDiscordBotConfig,
  useDiscordGuilds,
} from "@/app/admin/discord-bot/hooks";
import { createBotConfig, deleteBotConfig } from "@/app/admin/discord-bot/lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import { getFormattedDateTime } from "@/lib/dateUtils";

interface Props {
  setPopup: (popup: PopupSpec) => void;
}

export function BotConfigCard({ setPopup }: Props) {
  const {
    data: botConfig,
    isLoading,
    isManaged,
    refreshBotConfig,
  } = useDiscordBotConfig();
  const { data: guilds } = useDiscordGuilds();

  const [botToken, setBotToken] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Don't render anything if managed externally (Cloud or env var)
  if (isManaged) {
    return null;
  }

  // Show loading while fetching initial state
  if (isLoading) {
    return (
      <Card>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
        >
          <Text mainContentEmphasis text05>
            Bot Token
          </Text>
        </Section>
        <ThreeDotsLoader />
      </Card>
    );
  }

  const isConfigured = botConfig?.configured ?? false;
  const hasServerConfigs = (guilds?.length ?? 0) > 0;

  const handleSaveToken = async () => {
    if (!botToken.trim()) {
      setPopup({ type: "error", message: "Please enter a bot token" });
      return;
    }

    setIsSubmitting(true);
    try {
      await createBotConfig(botToken.trim());
      setBotToken("");
      refreshBotConfig();
      setPopup({ type: "success", message: "Bot token saved successfully" });
    } catch (err) {
      setPopup({
        type: "error",
        message:
          err instanceof Error ? err.message : "Failed to save bot token",
      });
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteToken = async () => {
    setIsSubmitting(true);
    try {
      await deleteBotConfig();
      refreshBotConfig();
      setPopup({ type: "success", message: "Bot token deleted" });
    } catch (err) {
      setPopup({
        type: "error",
        message:
          err instanceof Error ? err.message : "Failed to delete bot token",
      });
    } finally {
      setIsSubmitting(false);
      setShowDeleteConfirm(false);
    }
  };

  return (
    <>
      {showDeleteConfirm && (
        <ConfirmEntityModal
          danger
          entityType="Discord bot token"
          entityName="Discord Bot Token"
          onClose={() => setShowDeleteConfirm(false)}
          onSubmit={handleDeleteToken}
          additionalDetails="This will disconnect your Discord bot. You will need to re-enter the token to use the bot again."
        />
      )}
      <Card>
        <Section flexDirection="row" justifyContent="between">
          <Section flexDirection="row" gap={0.5} width="fit">
            <Text mainContentEmphasis text05>
              Bot Token
            </Text>
            {isConfigured ? (
              <Badge variant="success">Configured</Badge>
            ) : (
              <Badge variant="secondary">Not Configured</Badge>
            )}
          </Section>
          {isConfigured && (
            <SimpleTooltip
              tooltip={
                hasServerConfigs ? "Delete server configs first" : undefined
              }
              disabled={!hasServerConfigs}
            >
              <Button
                onClick={() => setShowDeleteConfirm(true)}
                disabled={isSubmitting || hasServerConfigs}
                danger
              >
                Delete Discord Token
              </Button>
            </SimpleTooltip>
          )}
        </Section>

        {isConfigured ? (
          <Section flexDirection="column" alignItems="start" gap={0.5}>
            <Text text03 secondaryBody>
              Your Discord bot token is configured.
              {botConfig?.created_at && (
                <>
                  {" "}
                  Added {getFormattedDateTime(new Date(botConfig.created_at))}.
                </>
              )}
            </Text>
            <Text text03 secondaryBody>
              To change the token, delete the current one and add a new one.
            </Text>
          </Section>
        ) : (
          <Section flexDirection="column" alignItems="start" gap={0.75}>
            <Text text03 secondaryBody>
              Enter your Discord bot token to enable the bot. You can get this
              from the Discord Developer Portal.
            </Text>
            <Section flexDirection="row" alignItems="end" gap={0.5}>
              <PasswordInputTypeIn
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="Enter bot token..."
                disabled={isSubmitting}
                className="flex-1"
              />
              <Button
                onClick={handleSaveToken}
                disabled={isSubmitting || !botToken.trim()}
              >
                {isSubmitting ? "Saving..." : "Save Token"}
              </Button>
            </Section>
          </Section>
        )}
      </Card>
    </>
  );
}
