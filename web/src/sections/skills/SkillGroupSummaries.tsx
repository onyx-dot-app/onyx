"use client";

import { useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { useInstallationPolicyOptions } from "@/lib/skills/hooks";
import type { SkillGroupSummary } from "@/lib/skills/types";

const VISIBLE_GROUPS = 2;

interface SkillGroupSummariesProps {
  summaries: SkillGroupSummary[];
  /** One line of names for narrow rows that hide the Groups column. */
  compact?: boolean;
}

/** Groups the viewer may see. An empty list shows nothing: the server filters
 * summaries by authority, so it does not mean the skill has no groups. */
export default function SkillGroupSummaries({
  summaries,
  compact = false,
}: SkillGroupSummariesProps) {
  const t = useTranslations("skills.groups");
  const policyOptions = useInstallationPolicyOptions();
  if (summaries.length === 0) return null;
  const names = summaries.map((summary) => summary.group_name).join(", ");

  if (compact) {
    return (
      <Text
        font="secondary-body"
        color="text-03"
        as="p"
        maxLines={1}
        overflowTooltip
      >
        {t("compact", { count: summaries.length, names })}
      </Text>
    );
  }

  function groupDetail(summary: SkillGroupSummary) {
    const policy =
      policyOptions.find(({ value }) => value === summary.installation_policy)
        ?.label ?? null;
    return summary.source === "marketplace"
      ? policy
        ? t("marketplacePolicy", { policy })
        : t("marketplace")
      : policy;
  }

  const hidden = summaries.slice(VISIBLE_GROUPS);
  return (
    <Section
      height="auto"
      gap={0}
      alignItems="stretch"
      width={0}
      className="min-w-full"
    >
      {summaries.slice(0, VISIBLE_GROUPS).map((summary) => {
        const detail = groupDetail(summary);
        return (
          <Section key={summary.group_id} height="auto" alignItems="stretch">
            <Text
              font="main-ui-body"
              color="text-04"
              as="p"
              maxLines={1}
              overflowTooltip
            >
              {summary.group_name}
            </Text>
            {detail && (
              <Text
                font="secondary-body"
                color="text-03"
                as="p"
                maxLines={2}
                overflowTooltip
              >
                {detail}
              </Text>
            )}
          </Section>
        );
      })}
      {hidden.length > 0 && (
        <Text
          font="secondary-body"
          color="text-03"
          as="p"
          tabIndex={0}
          tooltip={hidden
            .map((summary) =>
              [summary.group_name, groupDetail(summary)]
                .filter(Boolean)
                .join(": ")
            )
            .join(", ")}
        >
          {t("more", { count: hidden.length })}
        </Text>
      )}
    </Section>
  );
}
