"use client";

import { useCallback, useMemo, useState } from "react";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgLink,
  SvgOrganization,
  SvgShare,
  SvgTag,
  SvgUsers,
  SvgX,
} from "@opal/icons";
import InputChipField from "@/refresh-components/inputs/InputChipField";
import Message from "@/refresh-components/messages/Message";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@/refresh-components/cards";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import * as InputLayouts from "@/layouts/input-layouts";
import SwitchField from "@/refresh-components/form/SwitchField";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgUser } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import useShareableUsers from "@/hooks/useShareableUsers";
import useShareableGroups from "@/hooks/useShareableGroups";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { useUser } from "@/providers/UserProvider";
import { Formik, useFormikContext } from "formik";
import { useAgent } from "@/hooks/useAgents";
import { Button as OpalButton } from "@opal/components";
import { useLabels } from "@/lib/hooks";
import { PersonaLabel } from "@/app/admin/assistants/interfaces";

const YOUR_ORGANIZATION_TAB = "Your Organization";
const USERS_AND_GROUPS_TAB = "Users & Groups";

// ============================================================================
// Types
// ============================================================================

interface ShareAgentFormValues {
  selectedUserIds: string[];
  selectedGroupIds: number[];
  isPublic: boolean;
  isFeatured: boolean;
  labelIds: number[];
}

// ============================================================================
// ShareAgentFormContent
// ============================================================================

interface ShareAgentFormContentProps {
  agentId?: number;
}

function ShareAgentFormContent({ agentId }: ShareAgentFormContentProps) {
  const { values, setFieldValue, handleSubmit, dirty } =
    useFormikContext<ShareAgentFormValues>();
  const { data: usersData } = useShareableUsers({ includeApiKeys: true });
  const { data: groupsData } = useShareableGroups();
  const { user: currentUser, isAdmin, isCurator } = useUser();
  const { agent: fullAgent } = useAgent(agentId ?? null);
  const shareAgentModal = useModal();
  const { labels: allLabels, createLabel } = useLabels();
  const [labelInputValue, setLabelInputValue] = useState("");

  const acceptedUsers = usersData ?? [];
  const groups = groupsData ?? [];
  const canUpdateFeaturedStatus = isAdmin || isCurator;

  // Create options for InputComboBox from all accepted users and groups
  const comboBoxOptions = useMemo(() => {
    const userOptions = acceptedUsers
      .filter((user) => user.id !== currentUser?.id)
      .map((user) => ({
        value: `user-${user.id}`,
        label: user.email,
      }));

    const groupOptions = groups.map((group) => ({
      value: `group-${group.id}`,
      label: group.name,
    }));

    return [...userOptions, ...groupOptions];
  }, [acceptedUsers, groups, currentUser?.id]);

  // Compute owner and displayed users
  const ownerId = fullAgent?.owner?.id;
  const owner = ownerId
    ? acceptedUsers.find((user) => user.id === ownerId)
    : acceptedUsers.find((user) => user.id === currentUser?.id);
  const otherUsers = owner
    ? acceptedUsers.filter(
        (user) =>
          user.id !== owner.id && values.selectedUserIds.includes(user.id)
      )
    : acceptedUsers;
  const displayedUsers = [...(owner ? [owner] : []), ...otherUsers];

  // Compute displayed groups based on current form values
  const displayedGroups = groups.filter((group) =>
    values.selectedGroupIds.includes(group.id)
  );

  // Handlers
  function handleClose() {
    shareAgentModal.toggle(false);
  }

  function handleCopyLink() {
    if (!agentId) return;
    const url = `${window.location.origin}/chat?assistantId=${agentId}`;
    navigator.clipboard.writeText(url);
  }

  function handleComboBoxSelect(selectedValue: string) {
    if (selectedValue.startsWith("user-")) {
      const userId = selectedValue.replace("user-", "");
      if (!values.selectedUserIds.includes(userId)) {
        setFieldValue("selectedUserIds", [...values.selectedUserIds, userId]);
      }
    } else if (selectedValue.startsWith("group-")) {
      const groupId = parseInt(selectedValue.replace("group-", ""));
      if (!values.selectedGroupIds.includes(groupId)) {
        setFieldValue("selectedGroupIds", [
          ...values.selectedGroupIds,
          groupId,
        ]);
      }
    }
  }

  function handleRemoveUser(userId: string) {
    setFieldValue(
      "selectedUserIds",
      values.selectedUserIds.filter((id) => id !== userId)
    );
  }

  function handleRemoveGroup(groupId: number) {
    setFieldValue(
      "selectedGroupIds",
      values.selectedGroupIds.filter((id) => id !== groupId)
    );
  }

  const selectedLabels: PersonaLabel[] = useMemo(() => {
    if (!allLabels) return [];
    return allLabels.filter((label) => values.labelIds.includes(label.id));
  }, [allLabels, values.labelIds]);

  function handleRemoveLabel(labelId: number) {
    setFieldValue(
      "labelIds",
      values.labelIds.filter((id) => id !== labelId)
    );
  }

  const addLabel = useCallback(
    async (name: string) => {
      const trimmed = name.trim();
      if (!trimmed) return;

      const existing = allLabels?.find(
        (l) => l.name.toLowerCase() === trimmed.toLowerCase()
      );
      if (existing) {
        if (!values.labelIds.includes(existing.id)) {
          setFieldValue("labelIds", [...values.labelIds, existing.id]);
        }
      } else {
        const newLabel = await createLabel(trimmed);
        if (newLabel) {
          setFieldValue("labelIds", [...values.labelIds, newLabel.id]);
        }
      }
      setLabelInputValue("");
    },
    [allLabels, values.labelIds, setFieldValue, createLabel]
  );

  const chipItems = useMemo(
    () =>
      selectedLabels.map((label) => ({
        id: String(label.id),
        label: label.name,
      })),
    [selectedLabels]
  );

  return (
    <Modal.Content width="sm" height="lg">
      <Modal.Header icon={SvgShare} title="Share Agent" onClose={handleClose} />

      <Modal.Body padding={0.5}>
        <Card variant="borderless" padding={0.5}>
          <Tabs
            defaultValue={
              values.isPublic ? YOUR_ORGANIZATION_TAB : USERS_AND_GROUPS_TAB
            }
          >
            <Tabs.List>
              <Tabs.Trigger icon={SvgUsers} value={USERS_AND_GROUPS_TAB}>
                {USERS_AND_GROUPS_TAB}
              </Tabs.Trigger>
              <Tabs.Trigger
                icon={SvgOrganization}
                value={YOUR_ORGANIZATION_TAB}
              >
                {YOUR_ORGANIZATION_TAB}
              </Tabs.Trigger>
            </Tabs.List>

            <Tabs.Content value={USERS_AND_GROUPS_TAB}>
              <Section gap={0.5} alignItems="start">
                <InputComboBox
                  placeholder="Add users and groups"
                  value=""
                  onChange={() => {}}
                  onValueChange={handleComboBoxSelect}
                  options={comboBoxOptions}
                  strict
                />
                {(displayedUsers.length > 0 || displayedGroups.length > 0) && (
                  <Section gap={0} alignItems="stretch">
                    {/* Shared Users */}
                    {displayedUsers.map((user) => {
                      const isOwner = fullAgent?.owner?.id === user.id;
                      const isCurrentUser = currentUser?.id === user.id;

                      return (
                        <LineItem
                          key={`user-${user.id}`}
                          icon={SvgUser}
                          description={isCurrentUser ? "You" : undefined}
                          rightChildren={
                            isOwner || (isCurrentUser && !agentId) ? (
                              // Owner will always have the agent "shared" with it.
                              // Therefore, we never render any `IconButton SvgX` to remove it.
                              //
                              // Note:
                              // This user, during creation, is assumed to be the "owner".
                              // That is why the `(isCurrentUser && !agent)` condition exists.
                              <Text secondaryBody text03>
                                Owner
                              </Text>
                            ) : (
                              // For all other cases (including for "self-unsharing"),
                              // we render an `IconButton SvgX` to remove a person from the list.
                              <OpalButton
                                prominence="tertiary"
                                size="sm"
                                icon={SvgX}
                                onClick={() => handleRemoveUser(user.id)}
                              />
                            )
                          }
                        >
                          {user.email}
                        </LineItem>
                      );
                    })}

                    {/* Shared Groups */}
                    {displayedGroups.map((group) => (
                      <LineItem
                        key={`group-${group.id}`}
                        icon={SvgUsers}
                        rightChildren={
                          <OpalButton
                            prominence="tertiary"
                            size="sm"
                            icon={SvgX}
                            onClick={() => handleRemoveGroup(group.id)}
                          />
                        }
                      >
                        {group.name}
                      </LineItem>
                    ))}
                  </Section>
                )}
              </Section>
              {values.isPublic && (
                <Section>
                  <Message
                    iconComponent={SvgOrganization}
                    close={false}
                    static
                    className="w-full"
                    text="This agent is public to your organization."
                    description="Everyone in your organization has access to this agent."
                  />
                </Section>
              )}
            </Tabs.Content>

            <Tabs.Content value={YOUR_ORGANIZATION_TAB} padding={0.5}>
              <Section gap={1} alignItems="stretch">
                <InputLayouts.Horizontal
                  title="Publish This Agent"
                  description="Make this agent available to everyone in your organization."
                >
                  <SwitchField name="isPublic" />
                </InputLayouts.Horizontal>

                {canUpdateFeaturedStatus && (
                  <>
                    <div className="border-t border-border-02" />

                    <InputLayouts.Horizontal
                      title="Feature This Agent"
                      description="Show this agent at the top of the explore agents list and automatically pin it to the sidebar for new users with access."
                    >
                      <SwitchField name="isFeatured" />
                    </InputLayouts.Horizontal>
                  </>
                )}

                <InputChipField
                  chips={chipItems}
                  onRemoveChip={(id) => handleRemoveLabel(Number(id))}
                  onAdd={addLabel}
                  value={labelInputValue}
                  onChange={setLabelInputValue}
                  placeholder="Add labels..."
                  icon={SvgTag}
                />
                <Text secondaryBody text04>
                  Add labels and categories to help people better discover this
                  agent.
                </Text>
              </Section>
            </Tabs.Content>
          </Tabs>
        </Card>
      </Modal.Body>

      <Modal.Footer>
        <BasicModalFooter
          left={
            agentId ? (
              <Button secondary leftIcon={SvgLink} onClick={handleCopyLink}>
                Copy Link
              </Button>
            ) : undefined
          }
          cancel={
            <Button secondary onClick={handleClose}>
              Done
            </Button>
          }
          submit={
            <Button onClick={() => handleSubmit()} disabled={!dirty}>
              Share
            </Button>
          }
        />
      </Modal.Footer>
    </Modal.Content>
  );
}

// ============================================================================
// ShareAgentModal
// ============================================================================

export interface ShareAgentModalProps {
  agentId?: number;
  userIds: string[];
  groupIds: number[];
  isPublic: boolean;
  isFeatured: boolean;
  labelIds: number[];
  onShare?: (
    userIds: string[],
    groupIds: number[],
    isPublic: boolean,
    isFeatured: boolean,
    labelIds: number[]
  ) => void;
}

export default function ShareAgentModal({
  agentId,
  userIds,
  groupIds,
  isPublic,
  isFeatured,
  labelIds,
  onShare,
}: ShareAgentModalProps) {
  const shareAgentModal = useModal();

  const initialValues: ShareAgentFormValues = {
    selectedUserIds: userIds,
    selectedGroupIds: groupIds,
    isPublic: isPublic,
    isFeatured: isFeatured,
    labelIds: labelIds,
  };

  function handleSubmit(values: ShareAgentFormValues) {
    onShare?.(
      values.selectedUserIds,
      values.selectedGroupIds,
      values.isPublic,
      values.isFeatured,
      values.labelIds
    );
  }

  return (
    <Modal open={shareAgentModal.isOpen} onOpenChange={shareAgentModal.toggle}>
      <Formik
        initialValues={initialValues}
        onSubmit={handleSubmit}
        enableReinitialize
      >
        <ShareAgentFormContent agentId={agentId} />
      </Formik>
    </Modal>
  );
}
