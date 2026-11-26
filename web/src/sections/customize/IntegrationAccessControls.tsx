"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Dropdown,
  InputSwitch,
  Text,
  Tooltip,
  type DropdownMenuItem,
} from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { SvgMoreHorizontal, SvgOrganization, SvgShare } from "@opal/icons";
import {
  publishIntegration,
  setIntegrationEnabled,
} from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";
import GenericConfirmModal from "@/sections/modals/GenericConfirmModal";
import IntegrationConnectButton from "@/sections/plugins/IntegrationConnectButton";
import ShareIntegrationModal from "@/sections/plugins/ShareIntegrationModal";

/** Why the user cannot use an integration, or null when the user can. */
export function useIntegrationStateCopy() {
  const t = useTranslations("integrations.memberState");
  return {
    label: (integration: Pick<MemberIntegration, "access">) =>
      t(`${integration.access.state}.label`),
    /** The reason for a muted state, or null. */
    reason: (integration: Pick<MemberIntegration, "access">): string | null => {
      const { state, owner_email } = integration.access;
      if (state === "turned_off") return t("turned_off.reason");
      if (state !== "no_access") return null;
      return owner_email
        ? t("no_access.reasonOwner", { owner: owner_email })
        : t("no_access.reason");
    },
  };
}

interface IntegrationSwitchProps {
  integration: MemberIntegration;
}

/** The user's on/off switch of an integration. On means on everywhere. */
export function IntegrationSwitch({ integration }: IntegrationSwitchProps) {
  const t = useTranslations("integrations.memberState");
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);
  const required = integration.access.installation_policy === "REQUIRED";

  async function change(enabled: boolean) {
    setBusy(true);
    try {
      await setIntegrationEnabled(integration.id, enabled);
      await mutate(SWR_KEYS.integrations);
    } catch (failure) {
      toast.error(
        failure instanceof Error ? failure.message : t("switch.failed")
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      width="auto"
      height="auto"
      onClick={(event) => event.stopPropagation()}
    >
      <Tooltip
        tooltip={required ? t("switch.required") : undefined}
        side="bottom"
      >
        <Section width="auto" height="auto">
          <InputSwitch
            aria-label={t("switch.label", { name: integration.name })}
            checked={integration.access.user_enabled}
            disabled={busy || required}
            onCheckedChange={(checked) => void change(checked)}
          />
        </Section>
      </Tooltip>
    </Section>
  );
}

interface IntegrationStateControlProps {
  integration: MemberIntegration;
  /** Where the OAuth callback returns when no waiting tab closes it. */
  returnPath: string;
}

/** The control of one member row: a switch for On and Turn on, Connect and
 * the switch for Sign in, and a muted reason for No access and Turned off. */
export function IntegrationStateControl({
  integration,
  returnPath,
}: IntegrationStateControlProps) {
  const copy = useIntegrationStateCopy();
  const reason = copy.reason(integration);
  if (reason !== null)
    return (
      <Text font="secondary-body" color="text-03" maxLines={2}>
        {reason}
      </Text>
    );
  return (
    <Section
      flexDirection="row"
      justifyContent="end"
      alignItems="center"
      width="auto"
      height="auto"
      gap={1}
    >
      {integration.access.state === "sign_in" && (
        <IntegrationConnectButton
          integration={integration}
          returnPath={returnPath}
        />
      )}
      <IntegrationSwitch integration={integration} />
    </Section>
  );
}

interface IntegrationMenuProps {
  integration: MemberIntegration;
}

/** "Share" and "Publish to org" for a user who manages a private
 * integration. Renders nothing when neither applies. */
export function IntegrationMenu({ integration }: IntegrationMenuProps) {
  const t = useTranslations("integrations.menu");
  const { mutate } = useSWRConfig();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_ACTIONS);
  const [sharing, setSharing] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const { can_manage, shared_with_everyone } = integration.access;
  if (!can_manage || shared_with_everyone) return null;

  async function publish() {
    setPublishing(false);
    try {
      await publishIntegration(integration.id);
      toast.success(t("publish.done", { name: integration.name }));
      await Promise.all([
        mutate(SWR_KEYS.integrations),
        mutate(SWR_KEYS.adminIntegrations),
      ]);
    } catch (failure) {
      toast.error(
        failure instanceof Error ? failure.message : t("publish.failed")
      );
    }
  }

  const items: DropdownMenuItem[] = [
    {
      kind: "action",
      id: "share",
      icon: SvgShare,
      title: t("share"),
      onSelect: () => setSharing(true),
    },
    {
      kind: "action",
      id: "publish",
      icon: SvgOrganization,
      title: t("publish.label"),
      tooltip: isGlobalHolder ? undefined : t("publish.blocked"),
      disabled: !isGlobalHolder,
      onSelect: () => setPublishing(true),
    },
  ];
  const label = t("label", { name: integration.name });

  return (
    <Section
      width="auto"
      height="auto"
      onClick={(event) => event.stopPropagation()}
    >
      <Dropdown align="end">
        <Dropdown.Trigger asChild>
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgMoreHorizontal}
            aria-label={label}
            tooltip={label}
          />
        </Dropdown.Trigger>
        <Dropdown.Data label={label} items={items} />
      </Dropdown>
      {sharing && (
        <ShareIntegrationModal
          integration={integration}
          onClose={() => setSharing(false)}
          onSaved={() => setSharing(false)}
        />
      )}
      {publishing && (
        <GenericConfirmModal
          title={t("publish.confirmTitle", { name: integration.name })}
          message={t("publish.confirmMessage")}
          confirmText={t("publish.label")}
          onClose={() => setPublishing(false)}
          onConfirm={() => void publish()}
        />
      )}
    </Section>
  );
}
