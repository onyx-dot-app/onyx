"use client";

import { useNavigation } from "@opal/navigation";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SettingsLayouts, toast, Section } from "@opal/layouts";
import { Content, InputHorizontal } from "@opal/layouts";
import { Card, InputSwitch, MessageCard } from "@opal/components";
import { Disabled } from "@opal/core";
import { usePlans, useTierAtLeast } from "@/lib/tiers/hooks";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { updateAdminSettings } from "@/lib/settings/svc";
import { Tier } from "@/lib/tiers/types";

const route = ADMIN_ROUTES.LLM_GATEWAY;

export default function LLMGatewayPage() {
  const t = useTranslations("admin.llmGateway");
  const plans = usePlans();
  const navigation = useNavigation();
  const settings = useSettings();
  const businessTier = useTierAtLeast(Tier.BUSINESS);
  const enabled = settings.llm_gateway_enabled ?? true;

  async function save(checked: boolean) {
    try {
      await updateAdminSettings({ llm_gateway_enabled: checked });
      navigation.refresh();
      await mutate(SWR_KEYS.settings);
    } catch {
      toast.error(t("toasts.settingsUpdateFailed"));
    }
  }

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={t("header.title")}
        description={t("header.description")}
        divider
      />
      <SettingsLayouts.Body>
        <Section gap={3} alignItems="stretch">
          <Content
            font="main-content-emphasis"
            title={t("access.title")}
            description={t("access.description")}
          />
          <Card border="solid" rounding={4}>
            <Disabled
              disabled={!businessTier}
              allowClick={businessTier}
              tooltip={!businessTier ? t("tierTooltip") : undefined}
            >
              <InputHorizontal
                title={t("access.toggle.title")}
                tag={!businessTier ? plans[Tier.BUSINESS].tag : undefined}
                description={t("access.toggle.description")}
                disabled={!businessTier}
                withLabel
              >
                <InputSwitch
                  id="llm_gateway_enabled"
                  checked={businessTier ? enabled : false}
                  onCheckedChange={(checked) => {
                    void save(checked);
                  }}
                  disabled={!businessTier}
                />
              </InputHorizontal>
            </Disabled>
          </Card>
          <MessageCard variant="info" title={t("scopeNote.title")} />
        </Section>
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
