"use client";

import { use, useState, useEffect, useCallback, useMemo } from "react";
import { cn } from "@opal/utils";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { toast } from "@/hooks/useToast";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";
import { SettingsLayouts } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { Callout } from "@/components/ui/callout";
import { Button, MessageCard } from "@opal/components";
import { SvgServer } from "@opal/icons";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import {
  useDiscordGuild,
  useDiscordChannels,
} from "@/app/admin/discord-bot/hooks";
import {
  updateGuildConfig,
  bulkUpdateChannelConfigs,
} from "@/app/admin/discord-bot/lib";
import { DiscordChannelsTable } from "@/app/admin/discord-bot/[guild-id]/DiscordChannelsTable";
import { DiscordChannelConfig } from "@/app/admin/discord-bot/types";
import { useAdminAgents } from "@/lib/agents/hooks";
import { Agent } from "@/lib/agents/types";

interface Props {
  params: Promise<{ "guild-id": string }>;
}

function GuildDetailContent({
  guildId,
  personas,
  localChannels,
  onChannelUpdate,
  handleEnableAll,
  handleDisableAll,
  disabled,
}: {
  guildId: number;
  personas: Agent[];
  localChannels: DiscordChannelConfig[];
  onChannelUpdate: (
    channelId: number,
    field:
      | "enabled"
      | "require_bot_invocation"
      | "thread_only_mode"
      | "persona_override_id",
    value: boolean | number | null
  ) => void;
  handleEnableAll: () => void;
  handleDisableAll: () => void;
  disabled: boolean;
}) {
  const {
    data: guild,
    isLoading: guildLoading,
    error: guildError,
  } = useDiscordGuild(guildId);
  const { isLoading: channelsLoading, error: channelsError } =
    useDiscordChannels(guildId);

  if (guildLoading) {
    return <ThreeDotsLoader />;
  }

  if (guildError || !guild) {
    return (
      <ErrorCallout
        errorTitle="加载服务器失败"
        errorMsg={guildError?.info?.detail || "未找到服务器"}
      />
    );
  }

  const isRegistered = !!guild.guild_id;

  return (
    <>
      {!isRegistered && (
        <Callout type="notice" title="等待注册">
          在你的 Discord 服务器中使用 !register 命令和注册码完成设置。
        </Callout>
      )}

      <Card variant={disabled ? "disabled" : "primary"}>
        <ContentAction
          title="频道配置"
          description="在 Discord 中运行 !sync-channels 以更新频道列表。"
          sizePreset="main-content"
          variant="section"
          rightChildren={
            isRegistered && !channelsLoading && !channelsError ? (
              <Section
                flexDirection="row"
                justifyContent="end"
                alignItems="center"
                width="fit"
                gap={0.5}
              >
                <Button
                  disabled={disabled}
                  prominence="secondary"
                  onClick={handleEnableAll}
                >
                  全部启用
                </Button>
                <Button
                  disabled={disabled}
                  prominence="secondary"
                  onClick={handleDisableAll}
                >
                  全部禁用
                </Button>
              </Section>
            ) : undefined
          }
        />

        {!isRegistered ? (
          <Text text03 secondaryBody>
            服务器注册完成后即可配置频道。
          </Text>
        ) : channelsLoading ? (
          <ThreeDotsLoader />
        ) : channelsError ? (
          <ErrorCallout
            errorTitle="加载频道失败"
            errorMsg={channelsError?.info?.detail || "无法加载频道"}
          />
        ) : (
          <DiscordChannelsTable
            channels={localChannels}
            personas={personas}
            onChannelUpdate={onChannelUpdate}
            disabled={disabled}
          />
        )}
      </Card>
    </>
  );
}

export default function Page({ params }: Props) {
  const unwrappedParams = use(params);
  const guildId = Number(unwrappedParams["guild-id"]);
  const { data: guild, refreshGuild } = useDiscordGuild(guildId);
  const {
    data: channels,
    isLoading: channelsLoading,
    error: channelsError,
    refreshChannels,
  } = useDiscordChannels(guildId);
  const { agents, isLoading: personasLoading } = useAdminAgents(
    false,
    false,
    true
  );
  const [isUpdating, setIsUpdating] = useState(false);

  // Local state for channel configurations
  const [localChannels, setLocalChannels] = useState<DiscordChannelConfig[]>(
    []
  );

  // Track the original server state to detect changes
  const [originalChannels, setOriginalChannels] = useState<
    DiscordChannelConfig[]
  >([]);

  // Sync local state with fetched channels
  useEffect(() => {
    if (channels) {
      setLocalChannels(channels);
      setOriginalChannels(channels);
    }
  }, [channels]);

  // Check if there are unsaved changes
  const hasUnsavedChanges = useMemo(() => {
    for (const local of localChannels) {
      const original = originalChannels.find((c) => c.id === local.id);
      if (!original) return true;
      if (
        local.enabled !== original.enabled ||
        local.require_bot_invocation !== original.require_bot_invocation ||
        local.thread_only_mode !== original.thread_only_mode ||
        local.persona_override_id !== original.persona_override_id
      ) {
        return true;
      }
    }
    return false;
  }, [localChannels, originalChannels]);

  // Get list of changed channels for bulk update
  const getChangedChannels = useCallback(() => {
    const changes: {
      channelConfigId: number;
      update: {
        enabled: boolean;
        require_bot_invocation: boolean;
        thread_only_mode: boolean;
        persona_override_id: number | null;
      };
    }[] = [];

    for (const local of localChannels) {
      const original = originalChannels.find((c) => c.id === local.id);
      if (!original) continue;
      if (
        local.enabled !== original.enabled ||
        local.require_bot_invocation !== original.require_bot_invocation ||
        local.thread_only_mode !== original.thread_only_mode ||
        local.persona_override_id !== original.persona_override_id
      ) {
        changes.push({
          channelConfigId: local.id,
          update: {
            enabled: local.enabled,
            require_bot_invocation: local.require_bot_invocation,
            thread_only_mode: local.thread_only_mode,
            persona_override_id: local.persona_override_id,
          },
        });
      }
    }

    return changes;
  }, [localChannels, originalChannels]);

  const handleChannelUpdate = useCallback(
    (
      channelId: number,
      field:
        | "enabled"
        | "require_bot_invocation"
        | "thread_only_mode"
        | "persona_override_id",
      value: boolean | number | null
    ) => {
      setLocalChannels((prev) =>
        prev.map((channel) =>
          channel.id === channelId ? { ...channel, [field]: value } : channel
        )
      );
    },
    []
  );

  const handleEnableAll = useCallback(() => {
    setLocalChannels((prev) =>
      prev.map((channel) => ({ ...channel, enabled: true }))
    );
  }, []);

  const handleDisableAll = useCallback(() => {
    setLocalChannels((prev) =>
      prev.map((channel) => ({ ...channel, enabled: false }))
    );
  }, []);

  const handleSaveChanges = async () => {
    const changes = getChangedChannels();
    if (changes.length === 0) return;

    setIsUpdating(true);
    try {
      const { succeeded, failed } = await bulkUpdateChannelConfigs(
        guildId,
        changes
      );

      if (failed > 0) {
        toast.error(`已更新 ${succeeded} 个频道，但 ${failed} 个失败`);
        // Refresh to get actual server state when some updates failed
        refreshChannels();
      } else {
        toast.success(
          `已更新 ${succeeded} 个频道`
        );
        // Update original to match local (avoids flash from refresh)
        setOriginalChannels(localChannels);
      }
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "更新频道失败"
      );
    } finally {
      setIsUpdating(false);
    }
  };

  const handleDefaultPersonaChange = async (personaId: number | null) => {
    if (!guild) return;
    setIsUpdating(true);
    try {
      await updateGuildConfig(guildId, {
        enabled: guild.enabled,
        default_persona_id: personaId,
      });
      refreshGuild();
      toast.success(
        personaId ? "默认智能体已更新" : "默认智能体已清除"
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "更新智能体失败"
      );
    } finally {
      setIsUpdating(false);
    }
  };

  const registeredText = guild?.registered_at
    ? `已注册：${new Date(guild.registered_at).toLocaleString()}`
    : "等待注册";

  const isRegistered = !!guild?.guild_id;
  const isUpdateDisabled =
    !isRegistered ||
    channelsLoading ||
    !!channelsError ||
    !hasUnsavedChanges ||
    !guild?.enabled ||
    isUpdating;

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgServer}
        title={guild?.guild_name || `服务器 #${guildId}`}
        description={registeredText}
        backButton
        rightChildren={
          <Button disabled={isUpdateDisabled} onClick={handleSaveChanges}>
            更新配置
          </Button>
        }
      />
      <SettingsLayouts.Body>
        {/* Default Agent Selector */}
        <Card variant={!guild?.enabled ? "disabled" : "primary"}>
          <ContentAction
            title="默认智能体"
            description="除非频道单独覆盖，否则机器人会在所有频道中使用此智能体。"
            sizePreset="main-content"
            variant="section"
            rightChildren={
              <InputSelect
                value={guild?.default_persona_id?.toString() ?? "default"}
                onValueChange={(value: string) =>
                  handleDefaultPersonaChange(
                    value === "default" ? null : parseInt(value)
                  )
                }
                disabled={isUpdating || !guild?.enabled || personasLoading}
              >
                <InputSelect.Trigger placeholder="选择智能体" />
                <InputSelect.Content>
                  <InputSelect.Item value="default">
                    默认智能体
                  </InputSelect.Item>
                  {agents.map((persona) => (
                    <InputSelect.Item
                      key={persona.id}
                      value={persona.id.toString()}
                    >
                      {persona.name}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            }
          />
        </Card>

        <GuildDetailContent
          guildId={guildId}
          personas={agents}
          localChannels={localChannels}
          onChannelUpdate={handleChannelUpdate}
          handleEnableAll={handleEnableAll}
          handleDisableAll={handleDisableAll}
          disabled={!guild?.enabled}
        />

        {/* Unsaved changes indicator - sticky at bottom, centered in content area */}
        <div
          className={cn(
            "sticky z-toast bottom-4 w-fit mx-auto transition-all duration-300 ease-in-out",
            hasUnsavedChanges &&
              isRegistered &&
              !channelsLoading &&
              guild?.enabled
              ? "opacity-100 translate-y-0"
              : "opacity-0 translate-y-4 pointer-events-none"
          )}
        >
          <MessageCard
            variant="warning"
            title="你有未保存的更改"
            description="点击“更新”以保存。"
          />
        </div>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
