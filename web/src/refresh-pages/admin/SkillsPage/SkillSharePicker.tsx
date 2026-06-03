"use client";

import { useMemo } from "react";
import { SvgOrganization, SvgUsers, SvgX } from "@opal/icons";
import { Button, Card, MessageCard, Switch, Tabs } from "@opal/components";
import { ContentAction, InputHorizontal } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import { Section } from "@/layouts/general-layouts";
import useShareableGroups from "@/hooks/useShareableGroups";

const GROUPS_TAB = "Groups";
const YOUR_ORGANIZATION_TAB = "Your Organization";

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
            {GROUPS_TAB}
          </Tabs.Trigger>
          <Tabs.Trigger icon={SvgOrganization} value={YOUR_ORGANIZATION_TAB}>
            {YOUR_ORGANIZATION_TAB}
          </Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value={GROUPS_TAB}>
          <Section gap={0.5} alignItems="start">
            <div className="w-full">
              <InputComboBox
                placeholder="Add a group..."
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
                No user groups exist yet. Create groups in /admin/groups to
                share skills with specific groups.
              </Text>
            )}
          </Section>
          {isPublic && (
            <Section>
              <MessageCard
                icon={SvgOrganization}
                title="This skill is public to your organization."
                description="Everyone in your organization has access to this skill."
              />
            </Section>
          )}
        </Tabs.Content>

        <Tabs.Content value={YOUR_ORGANIZATION_TAB}>
          <Section gap={1} alignItems="stretch" padding={0.5}>
            <InputHorizontal
              title="Publish This Skill"
              description="Make this skill available to everyone in your organization."
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
