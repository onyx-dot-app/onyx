"use client";

import { useMemo } from "react";
import { MinimalPersonaSnapshot } from "@/app/admin/assistants/interfaces";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import Button from "@/refresh-components/buttons/Button";
import {
  SvgCheck,
  SvgLink,
  SvgOrganization,
  SvgShare,
  SvgUsers,
} from "@opal/icons";
import Tabs from "@/refresh-components/Tabs";
import { Card } from "@/refresh-components/cards";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
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
import useFilter from "@/hooks/useFilter";
import { Formik } from "formik";
import { useAgent } from "@/hooks/useAgents";

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

  // Fetch full agent data
  const { agent: fullAgent, isLoading } = useAgent(agent?.id ?? null);

  // Filter out current user from the list
  const usersWithoutCurrent = useMemo(
    () =>
      (usersData?.accepted ?? []).filter((user) => user.id !== currentUser?.id),
    [usersData?.accepted, currentUser?.id]
  );

  // Use separate useFilter for users and groups
  const {
    query,
    setQuery: setUserSearchQuery,
    filtered: filteredUsers,
  } = useFilter(usersWithoutCurrent, (user) => user.email);
  const { setQuery: setGroupSearchQuery, filtered: filteredGroups } = useFilter(
    groupsData ?? [],
    (group) => group.name
  );

  const initialValues = {
    selectedUserIds: fullAgent?.users?.map((u) => u.id) ?? [],
    selectedGroupIds: fullAgent?.groups ?? [],
    isPublic: fullAgent?.is_public ?? true,
  };

  function handleCopyLink() {
    if (!agent?.id) return;

    const url = `${window.location.origin}/chat?assistantId=${agent.id}`;
    navigator.clipboard.writeText(url);
  }

  if (isLoading || !fullAgent) {
    return (
      <Modal.Content tall>
        <Modal.Header
          icon={SvgShare}
          title="Share Agent"
          onClose={() => shareAgentModal.toggle(false)}
        />
        <Modal.Body padding={0.5}>
          <Text>Loading...</Text>
        </Modal.Body>
      </Modal.Content>
    );
  }

  return (
    <Formik
      initialValues={initialValues}
      onSubmit={(values) => {
        onShare?.(
          values.selectedUserIds,
          values.selectedGroupIds,
          values.isPublic
        );
        shareAgentModal.toggle(false);
      }}
      enableReinitialize
    >
      {({ values, setFieldValue, handleSubmit, resetForm, dirty }) => {
        function handleClose() {
          resetForm();
          shareAgentModal.toggle(false);
        }

        return (
          <Modal.Content tall>
            <Modal.Header
              icon={SvgShare}
              title="Share Agent"
              onClose={handleClose}
            />

            <Modal.Body padding={0.5}>
              <Card borderless padding={0.5}>
                <Tabs defaultValue="Users & Groups">
                  <Tabs.List>
                    <Tabs.Trigger icon={SvgUsers} value="Users & Groups">
                      Users &amp; Groups
                    </Tabs.Trigger>
                    <Tabs.Trigger
                      icon={SvgOrganization}
                      value="Your Organization"
                    >
                      Your Organization
                    </Tabs.Trigger>
                  </Tabs.List>

                  <Tabs.Content value="Users & Groups">
                    <Section gap={0.5} alignItems="start">
                      <InputTypeIn
                        placeholder="Add users, groups, and accounts"
                        value={query}
                        onChange={(e) => {
                          const newQuery = e.target.value;
                          setUserSearchQuery(newQuery);
                          setGroupSearchQuery(newQuery);
                        }}
                      />
                      {(filteredUsers.length > 0 ||
                        filteredGroups.length > 0) && (
                        <Section gap={0.25} alignItems="stretch">
                          {filteredUsers.map((user) => {
                            const isSelected = values.selectedUserIds.includes(
                              user.id
                            );
                            const isOwner = agent?.owner?.id === user.id;
                            return (
                              <LineItem
                                key={`user-${user.id}`}
                                icon={isSelected ? SvgCheck : SvgUser}
                                selected={isSelected}
                                onClick={() => {
                                  const newUserIds = isSelected
                                    ? values.selectedUserIds.filter(
                                        (id) => id !== user.id
                                      )
                                    : [...values.selectedUserIds, user.id];
                                  setFieldValue("selectedUserIds", newUserIds);
                                }}
                                rightChildren={
                                  isOwner ? (
                                    <Text as="p" mainUiMuted text03>
                                      Owner
                                    </Text>
                                  ) : undefined
                                }
                              >
                                {user.email}
                              </LineItem>
                            );
                          })}
                          {filteredGroups.map((group) => {
                            const isSelected = values.selectedGroupIds.includes(
                              group.id
                            );
                            return (
                              <LineItem
                                key={`group-${group.id}`}
                                icon={isSelected ? SvgCheck : SvgUsers}
                                selected={isSelected}
                                onClick={() => {
                                  const newGroupIds = isSelected
                                    ? values.selectedGroupIds.filter(
                                        (id) => id !== group.id
                                      )
                                    : [...values.selectedGroupIds, group.id];
                                  setFieldValue(
                                    "selectedGroupIds",
                                    newGroupIds
                                  );
                                }}
                              >
                                {group.name}
                              </LineItem>
                            );
                          })}
                        </Section>
                      )}
                    </Section>
                  </Tabs.Content>
                  <Tabs.Content value="Your Organization" padding={0.5}>
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
                    <Button
                      secondary
                      leftIcon={SvgLink}
                      onClick={handleCopyLink}
                    >
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
      }}
    </Formik>
  );
}
