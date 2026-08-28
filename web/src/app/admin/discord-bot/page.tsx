"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { PageLoader } from "@opal/layouts";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Section } from "@/layouts/general-layouts";
import { SettingsLayouts, toast } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import { Modal } from "@opal/components";
import { CopyButton } from "@opal/components";
import Card from "@/refresh-components/cards/Card";
import { SvgKey, SvgPlusCircle } from "@opal/icons";
import {
  useDiscordGuilds,
  useDiscordBotConfig,
} from "@/app/admin/discord-bot/hooks";
import { createGuildConfig } from "@/app/admin/discord-bot/lib";
import { DiscordGuildsTable } from "@/app/admin/discord-bot/DiscordGuildsTable";
import { BotConfigCard } from "@/app/admin/discord-bot/BotConfigCard";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

const route = ADMIN_ROUTES.DISCORD_BOTS;

function DiscordBotContent() {
  const t = useTranslations("admin.discordBot");
  const { data: guilds, isLoading, error, refreshGuilds } = useDiscordGuilds();
  const { data: botConfig, isManaged } = useDiscordBotConfig();
  const [registrationKey, setRegistrationKey] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);

  // Bot is available if:
  // - Managed externally (Cloud/env) - assume it's configured
  // - Self-hosted and explicitly configured via UI
  const isBotAvailable = isManaged || botConfig?.configured === true;

  const handleCreateGuild = async () => {
    setIsCreating(true);
    try {
      const result = await createGuildConfig();
      setRegistrationKey(result.registration_key);
      refreshGuilds();
      toast.success(t("guilds.created.toast"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("guilds.createError.toast")
      );
    } finally {
      setIsCreating(false);
    }
  };

  if (isLoading) {
    return <PageLoader />;
  }

  if (error || !guilds) {
    return (
      <ErrorCallout
        errorTitle={t("error.loadServers.title")}
        errorMsg={error?.info?.detail || t("error.unknown.message")}
      />
    );
  }

  return (
    <>
      <BotConfigCard />

      <Modal open={!!registrationKey}>
        <Modal.Content width="sm">
          <Modal.Header
            title={t("registrationKey.header.title")}
            icon={SvgKey}
            onClose={() => setRegistrationKey(null)}
            description={t("registrationKey.header.description")}
          />
          <Modal.Body>
            <Text text04 mainUiBody>
              {t("registrationKey.instructions.text")}
            </Text>
            <Card variant="secondary">
              <Section
                flexDirection="row"
                justifyContent="between"
                alignItems="center"
              >
                <Text text03 secondaryMono>
                  !register {registrationKey}
                </Text>
                <CopyButton
                  getCopyText={() => `!register ${registrationKey}`}
                />
              </Section>
            </Card>
          </Modal.Body>
        </Modal.Content>
      </Modal>

      <Card variant={!isBotAvailable ? "disabled" : "primary"}>
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
        >
          <Text mainContentEmphasis text05>
            {t("serverConfigs.section.title")}
          </Text>
          <Button
            icon={SvgPlusCircle}
            prominence="secondary"
            onClick={handleCreateGuild}
            disabled={isCreating || !isBotAvailable}
          >
            {isCreating
              ? t("serverConfigs.addButton.creating.label")
              : t("serverConfigs.addButton.label")}
          </Button>
        </Section>
        <DiscordGuildsTable guilds={guilds} onRefresh={refreshGuilds} />
      </Card>
    </>
  );
}

export default function Page() {
  const t = useTranslations("admin.discordBot");

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={route.title}
        description={t("page.header.description")}
      />
      <SettingsLayouts.Body>
        <DiscordBotContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
