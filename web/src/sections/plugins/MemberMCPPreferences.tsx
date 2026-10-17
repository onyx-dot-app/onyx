"use client";

import { useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { InputSwitch, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import type {
  MCPServer,
  MCPServersResponse,
  MCPUserPreferencesRequest,
} from "@/lib/mcp/types";
import { saveMemberMCPPreferences } from "@/lib/plugins/member";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";

interface MemberMCPPreferencesProps {
  server: MCPServer;
  surface?: "all" | "craft";
}

export default function MemberMCPPreferences({
  server,
  surface = "all",
}: MemberMCPPreferencesProps) {
  const t = useTranslations("actions.memberPlugins.defaults");
  const availabilityCopy = useTranslations("actions.plugins.availability");
  const craftEnabled = useSettings().onyx_craft_enabled === true;
  const { mutate } = useSWRConfig();
  const { data, mutate: mutateServers } = useSWR<MCPServersResponse>(
    surface === "craft" ? SWR_KEYS.mcpServersCraft : SWR_KEYS.mcpServers,
    null,
    { revalidateOnMount: false }
  );
  const current =
    data?.mcp_servers.find((item) => item.id === server.id) ?? server;
  const [pending, setPending] = useState(false);
  const [failed, setFailed] = useState(false);
  const saving = useRef(false);

  async function save(preferences: MCPUserPreferencesRequest) {
    if (saving.current) return;
    saving.current = true;
    setPending(true);
    setFailed(false);
    try {
      if (!data) await mutateServers({ mcp_servers: [server] }, false);
      await saveMemberMCPPreferences(current.id, preferences, mutate);
    } catch {
      setFailed(true);
    } finally {
      saving.current = false;
      setPending(false);
    }
  }

  const rows = [
    ...(surface === "craft"
      ? []
      : [
          {
            key: "chat" as const,
            available: current.default_chat_enabled === true,
            checked: current.user_enabled_in_chat ?? true,
            onChange: (enabled: boolean) =>
              void save({ enabled_in_chat: enabled }),
          },
        ]),
    ...(craftEnabled
      ? [
          {
            key: "craft" as const,
            available: current.available_in_craft === true,
            checked: current.user_enabled_in_craft ?? true,
            onChange: (enabled: boolean) =>
              void save({ enabled_in_craft: enabled }),
          },
        ]
      : []),
  ];

  return (
    <Section padding={0} gap={4} alignItems="stretch" height="auto">
      {rows.map((row) => (
        <div key={row.key} className="flex items-start justify-between gap-4">
          <Content
            title={t(row.key)}
            description={
              row.available
                ? t(`${row.key}Description`)
                : t("unavailable", {
                    surface: availabilityCopy(
                      row.key === "chat" ? "mainChat" : "craft"
                    ),
                  })
            }
            sizePreset="main-ui"
            variant="section"
          />
          <InputSwitch
            aria-label={t(row.key)}
            checked={row.available && row.checked}
            disabled={pending || !row.available}
            onCheckedChange={row.onChange}
          />
        </div>
      ))}
      {failed && (
        <div role="alert">
          <Text font="secondary-body" color="status-error-05">
            {t("saveFailed")}
          </Text>
        </div>
      )}
    </Section>
  );
}
