"use client";

import { useMemo } from "react";
import { SvgOrganization, SvgUsers, SvgX } from "@opal/icons";
import { Button, Card, MessageCard, Switch, Tabs } from "@opal/components";
import { ContentAction, InputHorizontal } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import { Section } from "@/layouts/general-layouts";
import useShareableGroups from "@/hooks/useShareableGroups";

const GROUPS_TAB = "groups";
const YOUR_ORGANIZATION_TAB = "organization";

interface SkillSharePickerProps {
  isPublic: boolean;
  onIsPublicChange: (isPublic: boolean) => void;
  groupIds: number[];
  onGroupIdsChange: (groupIds: number[]) => void;
}

/**
 * Sharing picker for custom skills. Mirrors the layout of `ShareAgentModal`
 * — two tabs ("Groups" and "Your Organization") with a combobox + selected
 * list on the first tab and an org-wide switch on the second.
 *
 * Skills don't support per-user grants or featured/labels, so this is the
 * trimmed-down sibling of `ShareAgentModal`.
 */
export default function SkillSharePicker({
  isPublic,
  onIsPublicChange,
  groupIds,
  onGroupIdsChange,
}: SkillSharePickerProps) {
  const {
    data: groupsData,
    isLoading: groupsLoading,
    error: groupsError,
  } = useShareableGroups();
  const groups = groupsData ?? [];

  const comboBoxOptions = useMemo(
    () =>
      groups
        .filter((group) => !groupIds.includes(group.id))
        .map((group) => ({
          value: String(group.id),
          label: group.name,
        })),
    [groups, groupIds]
  );

  const selectedGroups = useMemo(
    () => groups.filter((group) => groupIds.includes(group.id)),
    [groups, groupIds]
  );

  function handleSelectGroup(selectedValue: string) {
    const groupId = parseInt(selectedValue, 10);
    if (Number.isNaN(groupId) || groupIds.includes(groupId)) return;
    onGroupIdsChange([...groupIds, groupId]);
  }

  function handleRemoveGroup(groupId: number) {
    onGroupIdsChange(groupIds.filter((id) => id !== groupId));
  }

  return (
    <Card padding="sm">
      <Tabs defaultValue={isPublic ? YOUR_ORGANIZATION_TAB : GROUPS_TAB}>
        <Tabs.List>
          <Tabs.Trigger icon={SvgUsers} value={GROUPS_TAB}>
            用户组
          </Tabs.Trigger>
          <Tabs.Trigger icon={SvgOrganization} value={YOUR_ORGANIZATION_TAB}>
            你的组织
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value={GROUPS_TAB}>
          <Section gap={0.5} alignItems="start">
            <div className="w-full">
              <InputComboBox
                placeholder="添加用户组..."
                value=""
                onChange={() => {}}
                onValueChange={handleSelectGroup}
                options={comboBoxOptions}
                strict
              />
            </div>
            {selectedGroups.length > 0 && (
              <Section gap={0} alignItems="stretch">
                {selectedGroups.map((group) => (
                  <ContentAction
                    key={`group-${group.id}`}
                    sizePreset="main-ui"
                    variant="section"
                    icon={SvgUsers}
                    title={group.name}
                    padding="sm"
                    rightChildren={
                      <Button
                        prominence="tertiary"
                        size="sm"
                        icon={SvgX}
                        onClick={() => handleRemoveGroup(group.id)}
                      />
                    }
                  />
                ))}
              </Section>
            )}
            {!groupsLoading && !groupsError && groups.length === 0 && (
              <Text as="span" secondaryBody text03>
                还没有用户组。请在 /admin/groups 创建用户组后，再将技能共享给指定用户组。
              </Text>
            )}
          </Section>
          {isPublic && (
            <Section>
              <MessageCard
                icon={SvgOrganization}
                title="此技能已对你的组织公开。"
                description="组织内所有成员都可以访问此技能。"
              />
            </Section>
          )}
        </Tabs.Content>

        <Tabs.Content value={YOUR_ORGANIZATION_TAB}>
          <Section gap={1} alignItems="stretch" padding={0.5}>
            <InputHorizontal
              title="发布此技能"
              description="让组织内所有成员都可以使用此技能。"
              withLabel
            >
              <Switch checked={isPublic} onCheckedChange={onIsPublicChange} />
            </InputHorizontal>
          </Section>
        </Tabs.Content>
      </Tabs>
    </Card>
  );
}
