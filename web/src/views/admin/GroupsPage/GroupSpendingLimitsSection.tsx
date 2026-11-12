"use client";

import { useTranslations } from "next-intl";
import { Collapsible, Text } from "@opal/components";
import { Disabled } from "@opal/core";
import { Section } from "@opal/layouts";
import type { RichStr } from "@opal/types";
import { PageLoader } from "@opal/loaders";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import {
  useGroupSpendingLimits,
  useModelOptions,
} from "@/lib/spendingLimits/hooks";
import { Permission } from "@/lib/types";
import { usePlans } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import {
  GroupCardKind,
  GroupLimitCard,
} from "@/views/admin/SpendingLimitsPage/GroupLimitCards";
import { withCardModels } from "@/views/admin/SpendingLimitsPage/modelOptions";

interface GroupSpendingLimitsSectionProps {
  groupId: number;
  /** Below Enterprise, or for a caller who doesn't manage the group. */
  disabled: boolean;
  disabledTooltip: string | RichStr;
}

/** The group's pool and per-member cards. Each card saves on its own, apart
 *  from the group form. */
export default function GroupSpendingLimitsSection({
  groupId,
  disabled,
  disabledTooltip,
}: GroupSpendingLimitsSectionProps) {
  const t = useTranslations("admin.spendingLimits");
  const plans = usePlans();
  const { isGlobalHolder: isAdmin } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  const { data, error, mutate } = useGroupSpendingLimits(
    disabled ? null : groupId
  );
  const baseModelOptions = useModelOptions();

  function body() {
    if (disabled) return null;
    if (error) {
      return <Text color="status-error-05">{t("page.loadFailed")}</Text>;
    }
    if (!data) return <PageLoader />;
    const modelOptions = withCardModels(baseModelOptions, [
      data.pool,
      data.per_member,
    ]);
    return (
      <Section gap={2} alignItems="stretch" height="auto">
        <GroupLimitCard
          kind={GroupCardKind.POOL}
          groupId={groupId}
          group={null}
          card={data.pool}
          modelOptions={modelOptions}
          canEdit
          onSaved={() => void mutate()}
        />
        <GroupLimitCard
          kind={GroupCardKind.PER_MEMBER}
          groupId={groupId}
          group={null}
          card={data.per_member}
          modelOptions={modelOptions}
          canEdit={isAdmin}
          onSaved={() => void mutate()}
        />
      </Section>
    );
  }

  return (
    <Collapsible
      title={t("groupPage.title")}
      description={t("groupPage.description")}
      tag={disabled ? plans[Tier.ENTERPRISE].tag : undefined}
    >
      <Disabled disabled={disabled} tooltip={disabledTooltip}>
        <div>{body()}</div>
      </Disabled>
    </Collapsible>
  );
}
