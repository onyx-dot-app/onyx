"use client";

import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  InputSingleSelect,
  type SelectOption,
} from "@opal/components";
import { Content, InputPadder, Section } from "@opal/layouts";
import { SvgMinusCircle, SvgUsers } from "@opal/icons";
import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import type { SkillInstallationPolicy } from "@/lib/skills/types";
import type { GroupAccessRow } from "@/lib/skills/sharing";
import {
  INHERIT,
  isPolicyChoice,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";
import { usePolicyOptions } from "@/lib/skills/hooks";

interface SkillGroupAccessProps {
  rows: GroupAccessRow[];
  /** The Organization setting a group with no setting uses; null while the
   * skill loads. */
  company: SkillInstallationPolicy | null;
  groups: MinimalUserGroupSnapshot[];
  disabled?: boolean;
  onChoice: (groupId: number, choice: PolicyChoice) => void;
  onAdd: (group: MinimalUserGroupSnapshot) => void;
  onRemove: (groupId: number) => void;
}

/** Claude's "Group access": one row for each group and its setting. A group
 * share keeps its row; choose the organization setting to clear it. */
export default function SkillGroupAccess({
  rows,
  company,
  groups,
  disabled = false,
  onChoice,
  onAdd,
  onRemove,
}: SkillGroupAccessProps) {
  const t = useTranslations("skills.modals.share.groupAccess");
  const options = usePolicyOptions({
    inherit: { scope: "group", policy: company },
  });
  // A group with a share cannot be Not available.
  const sharedOptions = options.filter(
    (option) => option.value !== "NOT_AVAILABLE"
  );
  const present = new Set(rows.map((row) => row.group_id));
  const candidates = groups.filter((group) => !present.has(group.id));

  return (
    <Section gap={3} height="auto" alignItems="stretch">
      <Content
        font="main-ui-action"
        title={t("title")}
        description={t("description")}
      />
      {rows.length > 0 && (
        <Card border="solid" padding={2}>
          <Section gap={1} height="auto" alignItems="stretch">
            {rows.map((row) => (
              <GroupPolicyRow
                key={row.group_id}
                name={row.group_name}
                description={
                  row.permission === null ? t("settingOnly") : t("shared")
                }
                value={row.choice}
                options={row.permission === null ? options : sharedOptions}
                disabled={disabled}
                onChange={(choice) => onChoice(row.group_id, choice)}
                onRemove={
                  row.permission === null
                    ? () => onRemove(row.group_id)
                    : undefined
                }
              />
            ))}
          </Section>
        </Card>
      )}
      {candidates.length > 0 && (
        <InputPadder>
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
              if (group) onAdd(group);
            }}
          />
        </InputPadder>
      )}
    </Section>
  );
}

interface GroupPolicyRowProps {
  name: string;
  description?: string;
  value: PolicyChoice;
  options: SelectOption[];
  disabled?: boolean;
  onChange: (choice: PolicyChoice) => void;
  /** Shows a remove button. Only a row that holds just a setting has one. */
  onRemove?: () => void;
}

/** One group and its setting, with a remove button for a setting-only row. */
function GroupPolicyRow({
  name,
  description,
  value,
  options,
  disabled = false,
  onChange,
  onRemove,
}: GroupPolicyRowProps) {
  const t = useTranslations("skills.modals.share.groupAccess");
  return (
    <Section
      role="group"
      aria-label={name}
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
          title={name}
          description={description}
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
            placeholder={t("select", { name })}
            value={value}
            defaultOption={INHERIT}
            options={options}
            disabled={disabled}
            onValueChange={(next) => {
              if (isPolicyChoice(next)) onChange(next);
            }}
          />
        </Section>
        {onRemove && (
          <Button
            icon={SvgMinusCircle}
            prominence="tertiary"
            tooltip={t("remove", { name })}
            aria-label={t("remove", { name })}
            disabled={disabled}
            onClick={onRemove}
          />
        )}
      </Section>
    </Section>
  );
}
