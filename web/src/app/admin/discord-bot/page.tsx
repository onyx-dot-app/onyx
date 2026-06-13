"use client";

import { useState } from "react";
import { ThreeDotsLoader } from "@/components/Loading";
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

const route = ADMIN_ROUTES.DISCORD_BOTS;

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
      toast.success("服务器配置已创建！");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "创建服务器失败"
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
        errorTitle="加载 Discord 服务器失败"
        errorMsg={error?.info?.detail || "发生未知错误"}
      />
    );
  }

  return (
    <>
      <BotConfigCard />

      <Modal open={!!registrationKey}>
        <Modal.Content width="sm">
          <Modal.Header
            title="注册码"
            icon={SvgKey}
            onClose={() => setRegistrationKey(null)}
            description="此 Key 只会显示一次！"
          />
          <Modal.Body>
            <Text text04 mainUiBody>
              复制命令，并在你的服务器任意文本频道中发送！
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
            服务器配置
          </Text>
          <Button
            icon={SvgPlusCircle}
            prominence="secondary"
            onClick={handleCreateGuild}
            disabled={isCreating || !isBotAvailable}
          >
            {isCreating ? "正在创建..." : "添加服务器"}
          </Button>
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
        icon={route.icon}
        title={route.title}
        description="将 Glomi AI 连接到你的 Discord 服务器。用户可以直接在 Discord 频道中提问。"
      />
      <SettingsLayouts.Body>
        <DiscordBotContent />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
