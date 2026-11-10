"use client";

import { useRef } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, Text } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { PageLoader } from "@opal/loaders";
import SvgNoResult from "@opal/illustrations/no-result";
import { isAuthStatusError, isNotFoundError } from "@/lib/fetcher";
import { useUserGroupSkills } from "@/lib/groupSkills/hooks";
import type {
  GroupInstallationPolicy,
  GroupSkillTarget,
} from "@/lib/groupSkills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import GroupSkillSettingRow, {
  groupSkillTarget,
  type GroupSkillRow,
} from "@/views/admin/GroupsPage/GroupSkillSettingRow";

interface GroupSkillsTabProps {
  groupId: number;
}

/** The group's install settings. Each row saves on its own; the page's
 *  Save action never sends them. */
export default function GroupSkillsTab({ groupId }: GroupSkillsTabProps) {
  const t = useTranslations("admin.groups.skills");
  const groupPolicyText = useTranslations(
    "skills.modals.share.groupInstallation"
  );
  const { mutate } = useSWRConfig();
  const { data, error, setPolicy } = useUserGroupSkills(groupId);
  const inFlightRef = useRef(0);
  const overlappedRef = useRef(false);

  // Each response replaces the list. When saves overlap, a late response can
  // predate another row's change, so refetch once the last one settles.
  async function save(
    target: GroupSkillTarget,
    policy: GroupInstallationPolicy | null
  ) {
    if (inFlightRef.current > 0) overlappedRef.current = true;
    inFlightRef.current += 1;
    try {
      await setPolicy(target, policy);
    } finally {
      inFlightRef.current -= 1;
      if (inFlightRef.current === 0 && overlappedRef.current) {
        overlappedRef.current = false;
        void mutate(SWR_KEYS.userGroupSkills(groupId));
      }
    }
  }

  if (error && (isAuthStatusError(error) || isNotFoundError(error))) {
    return (
      <IllustrationContent
        illustration={SvgNoResult}
        title={t("noAccess.title")}
        description={t("noAccess.description")}
      />
    );
  }
  const loadError = error ? (
    <Section height="auto" alignItems="start" gap={2}>
      <Text role="alert" color="status-error-05">
        {t("loadFailed")}
      </Text>
      <Button
        prominence="secondary"
        onClick={() => void mutate(SWR_KEYS.userGroupSkills(groupId))}
      >
        {t("retry.button")}
      </Button>
    </Section>
  ) : null;
  if (!data) return loadError ?? <PageLoader />;

  const marketplaces: GroupSkillRow[] = data.marketplaces.map((setting) => ({
    kind: "marketplace",
    setting,
  }));
  const skills: GroupSkillRow[] = data.skills.map((setting) => ({
    kind: "skill",
    setting,
  }));

  if (!error && marketplaces.length === 0 && skills.length === 0) {
    return (
      <IllustrationContent
        illustration={SvgNoResult}
        title={t("empty.title")}
        description={t("empty.description")}
      />
    );
  }

  function rowKey(row: GroupSkillRow): string {
    const target = groupSkillTarget(row);
    return `${target.kind}:${target.id}`;
  }

  return (
    <Section height="auto" alignItems="stretch" gap={6}>
      {loadError}
      <Section height="auto" alignItems="start" gap={1}>
        <Text font="main-ui-body" color="text-04" as="p">
          {t("intro")}
        </Text>
        <Text font="secondary-body" color="text-03" as="p">
          {groupPolicyText("description")}
        </Text>
      </Section>
      {[
        {
          key: "marketplaces",
          title: t("marketplaces.title"),
          description: t("marketplaces.description"),
          empty: t("marketplaces.empty"),
          rows: marketplaces,
        },
        {
          key: "skills",
          title: t("direct.title"),
          description: t("direct.description"),
          empty: t("direct.empty"),
          rows: skills,
        },
      ].map((section) => (
        <Section
          key={section.key}
          height="auto"
          alignItems="stretch"
          gap={2}
          role="region"
          aria-label={section.title}
        >
          <Section height="auto" alignItems="start" gap={0.5}>
            <Text font="main-ui-action" color="text-05" as="h3">
              {section.title}
            </Text>
            <Text font="secondary-body" color="text-03" as="p">
              {section.description}
            </Text>
          </Section>
          {section.rows.length === 0 ? (
            <Text font="secondary-body" color="text-03" as="p">
              {section.empty}
            </Text>
          ) : (
            section.rows.map((row) => (
              <GroupSkillSettingRow key={rowKey(row)} row={row} onSave={save} />
            ))
          )}
        </Section>
      ))}
    </Section>
  );
}
