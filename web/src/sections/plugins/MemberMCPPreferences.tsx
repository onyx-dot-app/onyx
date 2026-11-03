"use client";

import { useTranslations } from "next-intl";
import { InputSwitch, Tooltip } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import type { MCPServer, MCPUserPreferencesRequest } from "@/lib/mcp/types";
import { useSettings } from "@/lib/settings/hooks";

interface MemberMCPPreferencesProps {
  server: MCPServer;
  surface?: "all" | "craft";
  values: MCPUserPreferencesRequest;
  onChange: (preferences: MCPUserPreferencesRequest) => void;
  disabled?: boolean;
}

export default function MemberMCPPreferences({
  server,
  surface = "all",
  values,
  onChange,
  disabled = false,
}: MemberMCPPreferencesProps) {
  const t = useTranslations("actions.memberPlugins.defaults");
  const availabilityCopy = useTranslations("actions.plugins.availability");
  const craftEnabled = useSettings().onyx_craft_enabled === true;
  const rows = [
    ...(surface === "craft"
      ? []
      : [
          {
            key: "chat" as const,
            available: server.default_chat_enabled === true,
            checked: values.enabled_in_chat ?? true,
            onChange: (enabled: boolean) =>
              onChange({ enabled_in_chat: enabled }),
          },
        ]),
    ...(craftEnabled
      ? [
          {
            key: "craft" as const,
            available: server.available_in_craft === true,
            checked: values.enabled_in_craft ?? true,
            onChange: (enabled: boolean) =>
              onChange({ enabled_in_craft: enabled }),
          },
        ]
      : []),
  ];

  return (
    <Section padding={0} gap={4} alignItems="stretch" height="auto">
      {rows.map((row) => (
        <ContentAction
          key={row.key}
          title={t(row.key)}
          description={
            row.available
              ? t(`${row.key}Description`)
              : t(row.key === "chat" ? "chatUnavailable" : "unavailable", {
                  surface: availabilityCopy(
                    row.key === "chat" ? "mainChat" : "craft"
                  ),
                })
          }
          sizePreset="main-ui"
          variant="section"
          padding={0}
          rightChildren={
            <Tooltip
              tooltip={
                !row.available
                  ? t(row.key === "chat" ? "chatUnavailable" : "unavailable", {
                      surface: availabilityCopy(
                        row.key === "chat" ? "mainChat" : "craft"
                      ),
                    })
                  : undefined
              }
              side="top"
            >
              <InputSwitch
                aria-label={t(row.key)}
                checked={row.available && row.checked}
                disabled={disabled || !row.available}
                onCheckedChange={row.onChange}
              />
            </Tooltip>
          }
        />
      ))}
    </Section>
  );
}
