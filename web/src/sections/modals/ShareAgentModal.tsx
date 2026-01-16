"use client";

import { useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgLink,
  SvgOrganization,
  SvgShare,
  SvgUsers,
  SvgX,
} from "@opal/icons";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@/refresh-components/cards";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import * as InputLayouts from "@/layouts/input-layouts";
import SwitchField from "@/refresh-components/form/SwitchField";
import LineItem from "@/refresh-components/buttons/LineItem";
import { SvgUser } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import useUsers from "@/hooks/useUsers";
import useGroups from "@/hooks/useGroups";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { useUser } from "@/components/user/UserProvider";
import { Formik, useFormikContext } from "formik";
import { useAgent } from "@/hooks/useAgents";
import IconButton from "@/refresh-components/buttons/IconButton";
import { User } from "@/lib/types";
import { UserGroup } from "@/lib/types";
import { FullPersona } from "@/app/admin/assistants/interfaces";

const YOUR_ORGANIZATION_TAB = "Your Organization";
const USERS_AND_GROUPS_TAB = "Users & Groups";

// ============================================================================
// Types
// ============================================================================

interface ShareAgentFormValues {
  selectedUserIds: string[];
  selectedGroupIds: number[];
  isPublic: boolean;
}

interface ComboBoxOption {
  value: string;
  label: string;
}

// ============================================================================
// ShareAgentFormContent
// ============================================================================

interface ShareAgentFormContentProps {
  agent?: MinimalPersonaSnapshot;
  fullAgent: FullPersona | null;
  usersData: User[];
  groupsData: UserGroup[];
  currentUserId: string | undefined;
  comboBoxOptions: ComboBoxOption[];
  onClose: () => void;
  onCopyLink: () => void;
}

function ShareAgentFormContent({
  agent,
  fullAgent,
  usersData,
  groupsData,
  currentUserId,
  comboBoxOptions,
  onClose,
  onCopyLink,
}: ShareAgentFormContentProps) {
  const { values, setFieldValue, handleSubmit, dirty } =
    useFormikContext<ShareAgentFormValues>();

  // Compute owner and displayed users
  const ownerId = fullAgent?.owner?.id;
  const owner = ownerId
    ? usersData.find((user) => user.id === ownerId)
    : usersData.find((user) => user.id === currentUserId);
  const otherUsers = owner
    ? usersData.filter(
        (user) =>
          user.id !== owner.id && values.selectedUserIds.includes(user.id)
      )
    : usersData;
  const displayedUsers = [...(owner ? [owner] : []), ...otherUsers];

  // Compute displayed groups based on current form values
  const displayedGroups = groupsData.filter((group) =>
    values.selectedGroupIds.includes(group.id)
  );

  // Handlers
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

  return (
    <Modal.Content width="sm" height="lg">
      <Modal.Header icon={SvgShare} title="Share Agent" onClose={onClose} />

      <Modal.Body padding={0.5}>
        <Card borderless padding={0.5}>
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
                      const isCurrentUser = currentUserId === user.id;

                      return (
                        <LineItem
                          key={`user-${user.id}`}
                          icon={SvgUser}
                          description={isCurrentUser ? "You" : undefined}
                          rightChildren={
                            isOwner || (isCurrentUser && !agent) ? (
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
                              <IconButton
                                internal
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
                          <IconButton
                            internal
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
            </Tabs.Content>

            <Tabs.Content value={YOUR_ORGANIZATION_TAB} padding={0.5}>
              <InputLayouts.Horizontal
                label="Publish This Agent"
                description="Make this agent available to everyone in your organization."
              >
                <SwitchField name="isPublic" />
              </InputLayouts.Horizontal>
            </Tabs.Content>
          </Tabs>
        </Card>
      </Modal.Body>

      <Modal.Footer>
        <BasicModalFooter
          left={
            agent ? (
              <Button secondary leftIcon={SvgLink} onClick={onCopyLink}>
                Copy Link
              </Button>
            ) : undefined
          }
          cancel={
            <Button secondary onClick={onClose}>
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
  agent?: MinimalPersonaSnapshot;
  onShare?: (userIds: string[], groupIds: number[], isPublic: boolean) => void;
}

export default function ShareAgentModal({
  agent,
  onShare,
}: ShareAgentModalProps) {
  const { data: usersData } = useUsers({ includeApiKeys: false });
  const { data: groupsData } = useGroups();
  const { user: currentUser } = useUser();
  const shareAgentModal = useModal();
  const { agent: fullAgent } = useAgent(agent?.id ?? null);

  // Create options for InputComboBox from all accepted users and groups
  const comboBoxOptions = useMemo(() => {
    const userOptions = (usersData?.accepted ?? []).map((user) => ({
      value: `user-${user.id}`,
      label: user.email,
    }));

    const groupOptions = (groupsData ?? []).map((group) => ({
      value: `group-${group.id}`,
      label: group.name,
    }));

    return [...userOptions, ...groupOptions];
  }, [usersData?.accepted, groupsData]);

  const initialValues: ShareAgentFormValues = {
    selectedUserIds: fullAgent?.users?.map((u) => u.id) ?? [],
    selectedGroupIds: fullAgent?.groups ?? [],
    isPublic: fullAgent?.is_public ?? true,
  };

  function handleSubmit(values: ShareAgentFormValues) {
    onShare?.(values.selectedUserIds, values.selectedGroupIds, values.isPublic);
    shareAgentModal.toggle(false);
  }

  function handleClose() {
    shareAgentModal.toggle(false);
  }

  function handleCopyLink() {
    if (!agent?.id) return;
    const url = `${window.location.origin}/chat?assistantId=${agent.id}`;
    navigator.clipboard.writeText(url);
  }

  return (
    <Modal open={shareAgentModal.isOpen} onOpenChange={shareAgentModal.toggle}>
      <Formik
        initialValues={initialValues}
        onSubmit={handleSubmit}
        enableReinitialize
      >
        <ShareAgentFormContent
          agent={agent}
          fullAgent={fullAgent}
          usersData={usersData?.accepted ?? []}
          groupsData={groupsData ?? []}
          currentUserId={currentUser?.id}
          comboBoxOptions={comboBoxOptions}
          onClose={handleClose}
          onCopyLink={handleCopyLink}
        />
      </Formik>
    </Modal>
  );
}
