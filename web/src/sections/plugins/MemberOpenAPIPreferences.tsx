"use client";

import { useTranslations } from "next-intl";
import { InputSwitch, Tooltip } from "@opal/components";
import { ContentAction, Section } from "@opal/layouts";
import type { ToolSnapshot } from "@/lib/tools/types";

interface MemberOpenAPIPreferencesProps {
  tool: ToolSnapshot;
  values: { enabled_in_chat: boolean };
  onChange: (preferences: { enabled_in_chat: boolean }) => void;
  disabled?: boolean;
}

export default function MemberOpenAPIPreferences({
  tool,
  values,
  onChange,
  disabled = false,
}: MemberOpenAPIPreferencesProps) {
  const t = useTranslations("actions.memberPlugins.defaults");
  const availabilityCopy = useTranslations("actions.plugins.availability");
  const available = tool.default_chat_enabled === true;

  return (
    <Section padding={0} gap={4} alignItems="stretch" height="auto">
      <ContentAction
        title={t("chat")}
        description={
          available
            ? t("chatDescription")
            : t("chatUnavailable", { surface: availabilityCopy("mainChat") })
        }
        sizePreset="main-ui"
        variant="section"
        padding={0}
        rightChildren={
          <Tooltip
            tooltip={
              !available
                ? t("chatUnavailable", {
                    surface: availabilityCopy("mainChat"),
                  })
                : undefined
            }
            side="top"
          >
            <InputSwitch
              aria-label={t("chat")}
              checked={available && values.enabled_in_chat}
              disabled={disabled || !available}
              onCheckedChange={(enabled) =>
                onChange({ enabled_in_chat: enabled })
              }
            />
          </Tooltip>
        }
      />
    </Section>
  );
}
