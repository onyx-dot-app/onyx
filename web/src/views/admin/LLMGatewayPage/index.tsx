"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { SettingsLayouts, toast } from "@opal/layouts";
import { Content, InputHorizontal } from "@opal/layouts";
import { Card, InputSwitch, MessageCard, Text } from "@opal/components";
import { SvgOrganization, SvgSimpleLoader } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useSettings } from "@/lib/settings/hooks";
import { updateAdminSettings } from "@/lib/settings/svc";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { LLM_GATEWAY_MIN_TIER } from "@/lib/tiers";

const route = ADMIN_ROUTES.LLM_GATEWAY;

export default function LLMGatewayPage() {
  const t = useTranslations("admin.llmGateway");
  const router = useRouter();
  const settings = useSettings();
  const tierAllowed: boolean = useTierAtLeast(LLM_GATEWAY_MIN_TIER);
  const enabled: boolean = settings.llm_gateway_enabled ?? true;

  async function save(checked: boolean) {
    try {
      await updateAdminSettings({ llm_gateway_enabled: checked });
      router.refresh();
      await mutate(SWR_KEYS.settings);
      toast.success(t("toasts.settingsUpdated"));
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
        {/* useSettings returns defaults while loading and on error, so the stored value is unknown. */}
        {settings.error ? (
          <Text font="main-ui-body" color="text-03">
            {t("settingsLoadError.description")}
          </Text>
        ) : settings.isLoading ? (
          <div className="flex justify-center py-12">
            <SvgSimpleLoader className="h-6 w-6" />
          </div>
        ) : (
          <Section gap={3} alignItems="stretch">
            <Content
              title={t("access.title")}
              description={t("access.description")}
              sizePreset="main-content"
              variant="section"
            />
            <Card border="solid" rounding={4}>
              <InputHorizontal
                title={t("access.toggle.title")}
                tag={
                  !tierAllowed
                    ? {
                        title: t("businessPlanTag.label"),
                        color: "amber",
                        icon: SvgOrganization,
                      }
                    : undefined
                }
                description={
                  tierAllowed
                    ? t("access.toggle.description")
                    : t("tierTooltip")
                }
                disabled={!tierAllowed}
                withLabel
              >
                <InputSwitch
                  id="llm_gateway_enabled"
                  checked={tierAllowed ? enabled : false}
                  onCheckedChange={(checked: boolean) => {
                    void save(checked);
                  }}
                  disabled={!tierAllowed}
                />
              </InputHorizontal>
            </Card>
            <MessageCard variant="info" title={t("scopeNote.title")} />
          </Section>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
