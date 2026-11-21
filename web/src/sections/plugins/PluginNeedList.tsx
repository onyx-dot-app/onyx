"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, Card, Text } from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { SvgPlug, SvgPlus } from "@opal/icons";
import { useNavigation, usePathname } from "@opal/navigation";
import { isPluginPagePath, newIntegrationHref } from "@/lib/customize/paths";
import { useMemberIntegrations } from "@/lib/integrations/hooks";
import { setIntegrationEnabled } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  liveNeedState,
  needAction,
  needTransport,
  type PluginNeedAction,
} from "@/lib/plugins/needs";
import type { PluginNeed } from "@/lib/plugins/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";

interface NeedActionControlProps {
  need: PluginNeed;
  action: PluginNeedAction;
  /** An organization-wide manager adds the integration for everyone. */
  canAddForOrganization: boolean;
  onChanged?: () => void;
}

function NeedActionControl({
  need,
  action,
  canAddForOrganization,
  onChanged,
}: NeedActionControlProps) {
  const t = useTranslations("plugins.needs");
  const { mutate } = useSWRConfig();
  const navigation = useNavigation();
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);

  async function turnOn(integration: MemberIntegration) {
    setBusy(true);
    try {
      await setIntegrationEnabled(integration.id, true);
      await mutate(SWR_KEYS.integrations);
      onChanged?.();
    } catch (failure) {
      toast.error(
        failure instanceof Error && failure.message
          ? failure.message
          : t("turnOn.failed", { name: integration.name })
      );
    } finally {
      setBusy(false);
    }
  }

  switch (action.kind) {
    case "none":
      return null;
    case "turnOn":
      return (
        <Button
          size="md"
          prominence="secondary"
          disabled={busy}
          aria-label={t("turnOn.ariaLabel", { name: need.name })}
          onClick={() => void turnOn(action.integration)}
        >
          {t("turnOn.label")}
        </Button>
      );
    case "signIn":
      return (
        <IntegrationConnectButton
          integration={action.integration}
          returnPath={pathname}
          onConnected={onChanged}
        />
      );
    case "add":
      return (
        <Button
          size="md"
          prominence="secondary"
          icon={SvgPlus}
          aria-label={t("add.ariaLabel", { name: need.name })}
          onClick={() => {
            if (!need.url) return;
            const returnTo = `${pathname}?tab=integrations`;
            navigation.go(
              newIntegrationHref(
                {
                  name: need.name,
                  serverUrl: need.url,
                  transport: needTransport(need),
                  forOrganization: canAddForOrganization,
                  returnTo: isPluginPagePath(returnTo) ? returnTo : undefined,
                },
                canAddForOrganization
              )
            );
          }}
        >
          {t("add.label")}
        </Button>
      );
    case "note":
      return (
        <Text font="secondary-body" color="text-03">
          {t(`note.${action.note}`)}
        </Text>
      );
    default: {
      const unhandled: never = action;
      return unhandled;
    }
  }
}

interface PluginNeedListProps {
  needs: readonly PluginNeed[];
  interactive: boolean;
  onChanged?: () => void;
}

export default function PluginNeedList({
  needs,
  interactive,
  onChanged,
}: PluginNeedListProps) {
  const t = useTranslations("plugins.needs");
  const integrations = useMemberIntegrations();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_ACTIONS
  );
  const canAddIntegrations = isGlobalHolder || isScopedManager;
  const byId = new Map(
    (integrations.data ?? []).map((integration) => [
      integration.id,
      integration,
    ])
  );

  return (
    <Section gap={2} alignItems="stretch" height="auto">
      {needs.map((need) => {
        const integration =
          need.integration_id === null
            ? undefined
            : byId.get(need.integration_id);
        const state = liveNeedState(need, integration);
        const action = needAction(state, integration, canAddIntegrations);
        return (
          <Card key={need.name} padding={2} aria-label={need.name}>
            <ContentAction
              icon={SvgPlug}
              font="main-ui-action"
              title={need.name}
              titleMaxLines={1}
              responsive={interactive}
              description={
                need.url ??
                (need.url_problem
                  ? t(`urlProblem.${need.url_problem}`)
                  : need.transport === "stdio"
                    ? t("localServer")
                    : t("noUrl"))
              }
              badge={{
                title: t(`state.${state}`),
                color: state === "on" ? "success" : "default",
              }}
              descriptionMaxLines={1}
              padding={1}
              rightChildren={
                interactive ? (
                  <Section width="auto" height="auto" justifyContent="center">
                    <NeedActionControl
                      need={need}
                      action={action}
                      canAddForOrganization={isGlobalHolder}
                      onChanged={onChanged}
                    />
                  </Section>
                ) : undefined
              }
            />
          </Card>
        );
      })}
    </Section>
  );
}
