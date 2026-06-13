"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { Button } from "@opal/components";
import { Badge } from "@/components/ui/badge";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { ThreeDotsLoader } from "@/components/Loading";
import { Tooltip } from "@opal/components";
import {
  useDiscordBotConfig,
  useDiscordGuilds,
} from "@/app/admin/discord-bot/hooks";
import { createBotConfig, deleteBotConfig } from "@/app/admin/discord-bot/lib";
import { toast } from "@/hooks/useToast";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import { getFormattedDateTime } from "@/lib/dateUtils";

export function BotConfigCard() {
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
      toast.error("请输入 Bot Token");
      return;
    }

    setIsSubmitting(true);
    try {
      await createBotConfig(botToken.trim());
      setBotToken("");
      refreshBotConfig();
      toast.success("Bot Token 已保存");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "保存 Bot Token 失败"
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
      toast.success("Bot Token 已删除");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "删除 Bot Token 失败"
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
          entityType="Discord Bot Token"
          entityName="Discord Bot Token"
          onClose={() => setShowDeleteConfirm(false)}
          onSubmit={handleDeleteToken}
          additionalDetails="这会断开你的 Discord Bot。若要再次使用，需要重新输入 Token。"
        />
      )}
      <Card>
        <Section flexDirection="row" justifyContent="between">
          <Section flexDirection="row" gap={0.5} width="fit">
            <Text mainContentEmphasis text05>
              Bot Token
            </Text>
            {isConfigured ? (
              <Badge variant="success">已配置</Badge>
            ) : (
              <Badge variant="secondary">未配置</Badge>
            )}
          </Section>
          {isConfigured && (
            <Tooltip
              tooltip={
                hasServerConfigs ? "请先删除服务器配置" : undefined
              }
            >
              <Button
                disabled={isSubmitting || hasServerConfigs}
                variant="danger"
                onClick={() => setShowDeleteConfirm(true)}
              >
                删除 Discord Token
              </Button>
            </Tooltip>
          )}
        </Section>

        {isConfigured ? (
          <Section flexDirection="column" alignItems="start" gap={0.5}>
            <Text text03 secondaryBody>
              你的 Discord Bot Token 已配置。
              {botConfig?.created_at && (
                <>
                  {" "}
                  添加于 {getFormattedDateTime(new Date(botConfig.created_at))}。
                </>
              )}
            </Text>
            <Text text03 secondaryBody>
              如需更改 Token，请删除当前 Token 后再添加新的 Token。
            </Text>
          </Section>
        ) : (
          <Section flexDirection="column" alignItems="start" gap={0.75}>
            <Text text03 secondaryBody>
              输入 Discord Bot Token 以启用 Bot。你可以从 Discord Developer Portal 获取它。
            </Text>
            <Section flexDirection="row" alignItems="end" gap={0.5}>
              <PasswordInputTypeIn
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="输入 Bot Token..."
                disabled={isSubmitting}
              />
              <Button
                disabled={isSubmitting || !botToken.trim()}
                onClick={handleSaveToken}
              >
                {isSubmitting ? "正在保存..." : "保存 Token"}
              </Button>
            </Section>
          </Section>
        )}
      </Card>
    </>
  );
}
