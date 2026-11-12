"use client";

import { useTranslations } from "next-intl";
import { Card, InputSingleSelect } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgUsers } from "@opal/icons";
import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import type { SkillInstallationPolicy } from "@/lib/skills/types";
import type { GroupAccessRow } from "@/lib/skills/sharing";
import { INHERIT, usePolicyOptions } from "@/lib/skills/installationPolicy";
import GroupPolicyRow from "@/sections/skills/GroupPolicyRow";

interface SkillGroupAccessProps {
  rows: GroupAccessRow[];
  /** The Organization setting a group with no setting uses; null when it
   * differs between skills. */
  company: SkillInstallationPolicy | null;
  groups: MinimalUserGroupSnapshot[];
  description: string;
  disabled?: boolean;
  onChange: (rows: GroupAccessRow[]) => void;
}

/** Claude's "Group access": one row for each group and its setting. A group
 * share keeps its row; choose the organization setting to clear it. */
export default function SkillGroupAccess({
  rows,
  company,
  groups,
  description,
  disabled = false,
  onChange,
}: SkillGroupAccessProps) {
  const t = useTranslations("skills.modals.share.groupAccess");
  const options = usePolicyOptions({
    inherit: { scope: "group", policy: company },
  });
  const present = new Set(rows.map((row) => row.group_id));
  const candidates = groups.filter((group) => !present.has(group.id));

  return (
    <Section gap={3} height="auto" alignItems="stretch">
      <Content
        font="main-ui-action"
        title={t("title")}
        description={description}
      />
      {rows.length > 0 && (
        <Card border="solid" padding={2}>
          <Section gap={1} height="auto" alignItems="stretch">
            {rows.map((row) => (
              <GroupPolicyRow
                key={row.group_id}
                name={row.group_name}
                icon={SvgUsers}
                description={
                  row.permission === null ? t("settingOnly") : t("shared")
                }
                value={row.choice}
                options={options}
                disabled={disabled}
                onChange={(choice) =>
                  onChange(
                    rows.map((current) =>
                      current.group_id === row.group_id
                        ? { ...current, choice }
                        : current
                    )
                  )
                }
                onRemove={
                  row.permission === null
                    ? () =>
                        onChange(
                          rows.filter(
                            (current) => current.group_id !== row.group_id
                          )
                        )
                    : undefined
                }
              />
            ))}
          </Section>
        </Card>
      )}
      {candidates.length > 0 && (
        <InputSingleSelect
          placeholder={t("add")}
          value=""
          search
          disabled={disabled}
          options={candidates.map((group) => ({
            value: String(group.id),
            title: group.name,
            icon: SvgUsers,
          }))}
          onValueChange={(value) => {
            const group = candidates.find(
              (candidate) => String(candidate.id) === value
            );
            if (!group) return;
            onChange([
              ...rows,
              {
                group_id: group.id,
                group_name: group.name,
                permission: null,
                choice: INHERIT,
              },
            ]);
          }}
        />
      )}
    </Section>
  );
}
