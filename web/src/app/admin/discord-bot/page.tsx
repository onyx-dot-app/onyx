"use client";

import { useState } from "react";
import { PageLoader } from "@/refresh-components/PageLoader";
import { ErrorCallout } from "@/components/ErrorCallout";
import { toast } from "@/hooks/useToast";
import { Section } from "@/layouts/general-layouts";
import { SettingsLayouts } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { Button } from "@opal/components";
import Modal from "@/refresh-components/Modal";
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

import { useTranslation } from "react-i18next";

const route = ADMIN_ROUTES.DISCORD_BOTS;

function DiscordBotContent() {
  const { t } = useTranslation();
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
      toast.success("Server configuration created!");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to create server"
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
        errorTitle={t("admin.bots.failed_load_discord_servers")}
        errorMsg={error?.info?.detail || "An unknown error occurred"}
      />
    );
  }

  return (
    <>
      <BotConfigCard />

      <Modal open={!!registrationKey}>
        <Modal.Content width="sm">
          <Modal.Header
            title={t("admin.bots.registration_key_title")}
            icon={SvgKey}
            onClose={() => setRegistrationKey(null)}
            description={t("admin.bots.registration_key_desc")}
          />
          <Modal.Body>
            <Text text04 mainUiBody>
              {t("admin.bots.registration_key_instruction")}
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
            {t("admin.bots.server_configurations")}
          </Text>
          <Button
            icon={SvgPlusCircle}
            prominence="secondary"
            onClick={handleCreateGuild}
            disabled={isCreating || !isBotAvailable}
          >
            {isCreating ? t("admin.bots.creating") : t("admin.bots.add_server")}
          </Button>
        </Section>
        <DiscordGuildsTable guilds={guilds} onRefresh={refreshGuilds} />
      </Card>
    </>
  );
}

export default function Page() {
  const { t } = useTranslation();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("admin.bots.discord_title")}
        description={t("admin.bots.discord_desc")}
      />
      <SettingsLayouts.Body>
        <DiscordBotContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
