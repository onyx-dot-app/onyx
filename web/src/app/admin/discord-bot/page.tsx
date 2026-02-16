"use client";

import { useState } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { toast } from "@/hooks/useToast";
import { Section } from "@/layouts/general-layouts";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Text from "@/refresh-components/texts/Text";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import Modal from "@/refresh-components/Modal";
import CopyIconButton from "@/refresh-components/buttons/CopyIconButton";
import Card from "@/refresh-components/cards/Card";
import { SvgKey } from "@opal/icons";
import {
  useDiscordGuilds,
  useDiscordBotConfig,
} from "@/app/admin/discord-bot/hooks";
import { createGuildConfig } from "@/app/admin/discord-bot/lib";
import { DiscordGuildsTable } from "@/app/admin/discord-bot/DiscordGuildsTable";
import { BotConfigCard } from "@/app/admin/discord-bot/BotConfigCard";
import { SvgDiscordMono } from "@opal/icons";

function DiscordBotContent() {
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
    return <ThreeDotsLoader />;
  }

  if (error || !guilds) {
    return (
      <ErrorCallout
        errorTitle="Failed to load Discord servers"
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
            title="Registration Key"
            icon={SvgKey}
            onClose={() => setRegistrationKey(null)}
            description="This key will only be shown once!"
          />
          <Modal.Body>
            <Text text04 mainUiBody>
              Copy the command and send it from any text channel in your server!
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
                <CopyIconButton
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
            Server Configurations
          </Text>
          <CreateButton
            onClick={handleCreateGuild}
            disabled={isCreating || !isBotAvailable}
          >
            {isCreating ? "Creating..." : "Add Server"}
          </CreateButton>
        </Section>
        <DiscordGuildsTable guilds={guilds} onRefresh={refreshGuilds} />
      </Card>
    </>
  );
}

export default function Page() {
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgDiscordMono}
        title="Discord Bots"
        description="Connect Onyx to your Discord servers. Users can ask questions directly in Discord channels."
      />
      <SettingsLayouts.Body>
        <DiscordBotContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
