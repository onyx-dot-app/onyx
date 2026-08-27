"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { Button, Card, PasswordInputTypeIn } from "@opal/components";
import { Badge } from "@/components/ui/badge";
import SvgSimpleLoader from "@opal/icons/simple-loader";
import { Tooltip } from "@opal/components";
import {
  useDiscordBotConfig,
  useDiscordGuilds,
} from "@/app/admin/discord-bot/hooks";
import { createBotConfig, deleteBotConfig } from "@/app/admin/discord-bot/lib";
import { toast } from "@opal/layouts";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import { getFormattedDateTime } from "@/lib/dateUtils";

export function BotConfigCard() {
  const t = useTranslations("admin.discordBot");
  const locale = useLocale();
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
      <Card border="solid" rounding={4}>
        <Section alignItems="start" height="fit">
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="center"
          >
            <Text mainContentEmphasis text05>
              {t("botToken.section.title")}
            </Text>
          </Section>
          <div className="flex justify-center">
            <SvgSimpleLoader className="h-6 w-6" />
          </div>
        </Section>
      </Card>
    );
  }

  const isConfigured = botConfig?.configured ?? false;
  const hasServerConfigs = (guilds?.length ?? 0) > 0;

  const handleSaveToken = async () => {
    if (!botToken.trim()) {
      toast.error(t("botToken.missing.toast"));
      return;
    }

    setIsSubmitting(true);
    try {
      await createBotConfig(botToken.trim());
      setBotToken("");
      refreshBotConfig();
      toast.success(t("botToken.saved.toast"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("botToken.saveError.toast")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleDeleteToken = async () => {
    setIsSubmitting(true);
    try {
      await deleteBotConfig();
      refreshBotConfig();
      toast.success(t("botToken.deleted.toast"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("botToken.deleteError.toast")
      );
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
          entityType={t("botToken.deleteModal.entityType")}
          entityName={t("botToken.deleteModal.entityName")}
          onClose={() => setShowDeleteConfirm(false)}
          onSubmit={handleDeleteToken}
          additionalDetails={t("botToken.deleteModal.additionalDetails")}
        />
      )}
      <Card border="solid" rounding={4}>
        <Section alignItems="start" height="fit">
          <Section flexDirection="row" justifyContent="between">
            <Section flexDirection="row" gap={2} width="fit">
              <Text mainContentEmphasis text05>
                {t("botToken.section.title")}
              </Text>
              {isConfigured ? (
                <Badge variant="success">
                  {t("botToken.configured.badge")}
                </Badge>
              ) : (
                <Badge variant="secondary">
                  {t("botToken.notConfigured.badge")}
                </Badge>
              )}
            </Section>
            {isConfigured && (
              <Tooltip
                tooltip={
                  hasServerConfigs
                    ? t("botToken.deleteButton.blocked.tooltip")
                    : undefined
                }
              >
                <Button
                  disabled={isSubmitting || hasServerConfigs}
                  variant="danger"
                  onClick={() => setShowDeleteConfirm(true)}
                >
                  {t("botToken.deleteButton.label")}
                </Button>
              </Tooltip>
            )}
          </Section>

          {isConfigured ? (
            <Section flexDirection="column" alignItems="start" gap={2}>
              <Text text03 secondaryBody>
                {botConfig?.created_at
                  ? t("botToken.configuredWithDate.text", {
                      date:
                        getFormattedDateTime(
                          new Date(botConfig.created_at),
                          locale
                        ) ?? "",
                    })
                  : t("botToken.configured.text")}
              </Text>
              <Text text03 secondaryBody>
                {t("botToken.changeInstructions.text")}
              </Text>
            </Section>
          ) : (
            <Section flexDirection="column" alignItems="start" gap={3}>
              <Text text03 secondaryBody>
                {t("botToken.enterInstructions.text")}
              </Text>
              <Section flexDirection="row" alignItems="end" gap={2}>
                <PasswordInputTypeIn
                  value={botToken}
                  onChange={(e) => setBotToken(e.target.value)}
                  placeholder={t("botToken.input.placeholder")}
                  disabled={isSubmitting}
                />
                <Button
                  disabled={isSubmitting || !botToken.trim()}
                  onClick={handleSaveToken}
                >
                  {isSubmitting
                    ? t("botToken.saveButton.saving.label")
                    : t("botToken.saveButton.label")}
                </Button>
              </Section>
            </Section>
          )}
        </Section>
      </Card>
    </>
  );
}
