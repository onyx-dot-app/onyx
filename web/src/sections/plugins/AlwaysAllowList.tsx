"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Badge,
  Button,
  InputSwitch,
  MessageCard,
  Text,
} from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
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
 * Each action that asks offers the user's "Don't ask me". */
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
    <Section gap={3} alignItems="stretch" height="auto">
      <Text as="p" font="secondary-body" color="text-03">
        {canSave ? t("description") : t("readOnlyDescription")}
      </Text>
      {data.actions.map((action) => {
        const saved = action.user_policy === "allow";
        // A saved grant stays visible after the admin stops new grants, so
        // the user can still turn it off.
        const asks =
          (canSave || saved) && action.effective_admin_policy === "ask";
        return (
          <ContentAction
            key={action.key}
            font="secondary-body"
            title={action.display_name}
            description={
              action.always_asks
                ? t("alwaysAsks")
                : action.description &&
                    action.description !== action.display_name
                  ? action.description
                  : undefined
            }
            padding={0}
            rightChildren={
              <Section
                flexDirection="row"
                justifyContent="end"
                alignItems="center"
                width="auto"
                height="auto"
                gap={2}
              >
                <Badge
                  size={5}
                  title={policyCopy(
                    `${POLICY_LABEL_KEYS[action.effective_admin_policy]}.label`
                  )}
                />
                {asks && (
                  <>
                    <Text font="secondary-body" color="text-03">
                      {t("switch.visibleLabel")}
                    </Text>
                    <InputSwitch
                      aria-label={t("switch.label", {
                        name: action.display_name,
                      })}
                      checked={saved}
                      disabled={
                        savingKey !== null ||
                        action.always_asks ||
                        (!canSave && !saved)
                      }
                      onCheckedChange={(checked) =>
                        void change(action, checked)
                      }
                    />
                  </>
                )}
              </Section>
            }
          />
        );
      })}
    </Section>
  );
}
