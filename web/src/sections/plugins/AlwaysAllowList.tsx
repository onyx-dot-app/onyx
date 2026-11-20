"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, InputSwitch, MessageCard, Text } from "@opal/components";
import { Content, ContentAction, Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { useMemberActionPolicies } from "@/lib/integrations/hooks";
import { saveAlwaysAllow } from "@/lib/integrations/svc";
import type { MemberAction, PolicyValue } from "@/lib/integrations/types";

const POLICY_LABEL_KEYS = {
  allow: "always",
  ask: "ask",
  blocked: "deny",
} as const satisfies Record<PolicyValue, string>;

interface AlwaysAllowListProps {
  integrationId: number;
}

/** The actions of one integration with the admin's Allow, Ask or Blocked.
 * Each action that asks offers the user's "Always allow". */
export default function AlwaysAllowList({
  integrationId,
}: AlwaysAllowListProps) {
  const t = useTranslations("plugins.member.alwaysAllow");
  const policyCopy = useTranslations("actions.policyToggle");
  const { data, error, isLoading, mutate } =
    useMemberActionPolicies(integrationId);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  if (isLoading) return <IconLoader />;
  if (error || !data)
    return (
      <Section alignItems="start" gap={2} height="auto">
        <MessageCard variant="error" title={t("loadFailed")} />
        <Button prominence="secondary" onClick={() => void mutate()}>
          {t("retry.label")}
        </Button>
      </Section>
    );
  if (data.actions.length === 0) return null;
  const canSave = data.users_can_save_always_allow;

  async function change(action: MemberAction, allow: boolean) {
    setSavingKey(action.key);
    try {
      await mutate(
        saveAlwaysAllow(integrationId, {
          [action.key]: allow ? "allow" : null,
        }),
        { revalidate: false }
      );
    } catch (saveError) {
      toast.error(
        saveError instanceof Error ? saveError.message : t("saveFailed")
      );
    } finally {
      setSavingKey(null);
    }
  }

  return (
    <Section gap={1} alignItems="stretch" height="auto">
      <Content
        font="secondary-action"
        title={canSave ? t("title") : t("readOnlyTitle")}
        description={canSave ? t("description") : t("readOnlyDescription")}
      />
      {data.actions.map((action) => {
        const asks = canSave && action.effective_admin_policy === "ask";
        return (
          <ContentAction
            key={action.key}
            font="secondary-body"
            title={action.display_name}
            description={
              action.always_asks
                ? t("alwaysAsks")
                : (action.description ?? undefined)
            }
            padding={1}
            rightChildren={
              <Section
                flexDirection="row"
                justifyContent="end"
                alignItems="center"
                width="auto"
                height="auto"
                gap={1}
              >
                <Text font="secondary-body" color="text-03">
                  {policyCopy(
                    `${POLICY_LABEL_KEYS[action.effective_admin_policy]}.label`
                  )}
                </Text>
                {asks && (
                  <InputSwitch
                    aria-label={t("switch.label", {
                      name: action.display_name,
                    })}
                    checked={action.user_policy === "allow"}
                    disabled={savingKey !== null || action.always_asks}
                    onCheckedChange={(checked) => void change(action, checked)}
                  />
                )}
              </Section>
            }
          />
        );
      })}
    </Section>
  );
}
