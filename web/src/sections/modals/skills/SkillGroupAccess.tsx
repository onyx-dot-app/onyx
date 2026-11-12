"use client";

import { useTranslations } from "next-intl";
import { Button, Card, InputSingleSelect } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgMinusCircle, SvgUsers } from "@opal/icons";
import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import type { SkillInstallationPolicy } from "@/lib/skills/types";
import type { GroupAccessRow } from "@/lib/skills/sharing";
import {
  INHERIT,
  isPolicyChoice,
  useGroupPolicyOptions,
} from "@/lib/skills/installationPolicy";

interface SkillGroupAccessProps {
  rows: GroupAccessRow[];
  /** The organization setting a group with no setting uses; null when it
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
  const { options } = useGroupPolicyOptions(company);
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
              <Section
                key={row.group_id}
                role="group"
                aria-label={row.group_name}
                flexDirection="row"
                justifyContent="between"
                wrap
                gap={2}
                height="auto"
                padding={1}
              >
                <Section
                  width="auto"
                  height="auto"
                  alignItems="start"
                  className="min-w-0 grow basis-40"
                >
                  <Content
                    icon={SvgUsers}
                    font="main-ui-body"
                    title={row.group_name}
                    description={
                      row.permission === null ? t("settingOnly") : t("shared")
                    }
                  />
                </Section>
                <Section
                  flexDirection="row"
                  width="auto"
                  height="auto"
                  gap={1}
                  className="min-w-0 grow basis-56"
                >
                  <Section width="full" height="auto" alignItems="stretch">
                    <InputSingleSelect
                      placeholder={t("select", { name: row.group_name })}
                      value={row.choice}
                      defaultOption={INHERIT}
                      options={options}
                      disabled={disabled}
                      onValueChange={(value) => {
                        if (!isPolicyChoice(value)) return;
                        onChange(
                          rows.map((current) =>
                            current.group_id === row.group_id
                              ? { ...current, choice: value }
                              : current
                          )
                        );
                      }}
                    />
                  </Section>
                  {row.permission === null && (
                    <Button
                      icon={SvgMinusCircle}
                      prominence="tertiary"
                      tooltip={t("remove", { name: row.group_name })}
                      aria-label={t("remove", { name: row.group_name })}
                      disabled={disabled}
                      onClick={() =>
                        onChange(
                          rows.filter(
                            (current) => current.group_id !== row.group_id
                          )
                        )
                      }
                    />
                  )}
                </Section>
              </Section>
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
