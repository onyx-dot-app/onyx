"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import {
  SvgLink,
  SvgOrganization,
  SvgShare,
  SvgTag,
  SvgUser,
  SvgUsers,
  SvgX,
} from "@opal/icons";
import InputChipField from "@/refresh-components/inputs/InputChipField";
import InputComboBox from "@/refresh-components/inputs/InputComboBox/InputComboBox";
import { ContentAction, InputHorizontal } from "@opal/layouts";
import SwitchField from "@/refresh-components/form/SwitchField";
import { Section } from "@/layouts/general-layouts";
import useShareableUsers from "@/hooks/useShareableUsers";
import useShareableGroups from "@/hooks/useShareableGroups";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { useUser } from "@/providers/UserProvider";
import { Formik, useFormikContext } from "formik";
import { useAgent, useLabels } from "@/lib/agents/hooks";
import {
  Button,
  Card,
  Divider,
  MessageCard,
  Tabs,
  Text,
} from "@opal/components";
import { Disabled } from "@opal/core";
import { AgentLabel } from "@/lib/agents/types";
import { FetchError } from "@/lib/fetcher";

const YOUR_ORGANIZATION_TAB = "你的组织";
const USERS_AND_GROUPS_TAB = "用户和用户组";

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
  const { values, setFieldValue, handleSubmit, dirty, isSubmitting } =
    useFormikContext<ShareAgentFormValues>();
  const { data: usersData, error: usersError } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: groupsData } = useShareableGroups();
  const userDirectoryRestricted =
    usersError instanceof FetchError && usersError.status === 403;
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
    const userOptions = userDirectoryRestricted
      ? []
      : acceptedUsers
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
  }, [acceptedUsers, groups, currentUser?.id, userDirectoryRestricted]);

  const comboBoxDisabled =
    userDirectoryRestricted && comboBoxOptions.length === 0;

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
    const url = `${window.location.origin}/chat?agentId=${agentId}`;
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

  const selectedLabels: AgentLabel[] = useMemo(() => {
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
      <Modal.Header icon={SvgShare} title="分享智能体" onClose={handleClose} />

      <Modal.Body padding={0.5}>
        <Card padding="sm">
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
                <Disabled
                  disabled={comboBoxDisabled}
                  tooltip={
                    comboBoxDisabled
                      ? "管理员已限制用户目录。请联系管理员，将此智能体分享给其他用户。"
                      : undefined
                  }
                >
                  <div className="w-full">
                    <InputComboBox
                      placeholder={
                        userDirectoryRestricted
                          ? "添加用户组"
                          : "添加用户和用户组"
                      }
                      value=""
                      onChange={() => {}}
                      onValueChange={handleComboBoxSelect}
                      options={comboBoxOptions}
                      strict
                      disabled={comboBoxDisabled}
                    />
                  </div>
                </Disabled>
                {(displayedUsers.length > 0 || displayedGroups.length > 0) && (
                  <Section gap={0} alignItems="stretch">
                    {/* Shared Users */}
                    {displayedUsers.map((user) => {
                      const isOwner = fullAgent?.owner?.id === user.id;
                      const isCurrentUser = currentUser?.id === user.id;

                      return (
                        <div key={`user-${user.id}`} className="p-1">
                          <ContentAction
                            sizePreset="main-ui"
                            variant="section"
                            icon={SvgUser}
                            title={user.email}
                            description={isCurrentUser ? "你" : undefined}
                            padding="fit"
                            rightChildren={
                              isOwner || (isCurrentUser && !agentId) ? (
                                // Owner will always have the agent "shared" with it.
                                // Therefore, we never render any SvgX button to remove it.
                                //
                                // Note:
                                // This user, during creation, is assumed to be the "owner".
                                // That is why the `(isCurrentUser && !agentId)` condition exists.
                                <Text font="secondary-body" color="text-03">
                                  所有者
                                </Text>
                              ) : (
                                // For all other cases (including for "self-unsharing"),
                                // we render a Button with SvgX to remove a person from the list.
                                <Button
                                  prominence="tertiary"
                                  size="sm"
                                  icon={SvgX}
                                  onClick={() => handleRemoveUser(user.id)}
                                />
                              )
                            }
                          />
                        </div>
                      );
                    })}

                    {/* Shared Groups */}
                    {displayedGroups.map((group) => (
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
              </Section>
              {values.isPublic && (
                <Section>
                  <MessageCard
                    icon={SvgOrganization}
                    title="此智能体已对你的组织公开。"
                    description="组织内所有人都可以访问此智能体。"
                  />
                </Section>
              )}
            </Tabs.Content>

            <Tabs.Content value={YOUR_ORGANIZATION_TAB}>
              <Section gap={1} alignItems="stretch" padding={0.5}>
                <InputHorizontal
                  title="发布此智能体"
                  description="让组织内所有人都可以使用此智能体。"
                  withLabel
                >
                  <SwitchField name="isPublic" />
                </InputHorizontal>

                {canUpdateFeaturedStatus && (
                  <>
                    <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                    <InputHorizontal
                      title="精选此智能体"
                      description="将此智能体显示在探索智能体列表顶部，并为有访问权限的新用户自动固定到侧边栏。"
                      withLabel
                    >
                      <SwitchField name="isFeatured" />
                    </InputHorizontal>
                  </>
                )}

                <Section gap={0.25} alignItems="stretch">
                  <InputChipField
                    chips={chipItems}
                    onRemoveChip={(id) => handleRemoveLabel(Number(id))}
                    onAdd={addLabel}
                    value={labelInputValue}
                    onChange={setLabelInputValue}
                    placeholder="添加标签..."
                    icon={SvgTag}
                  />
                  <Text font="secondary-body" color="text-03">
                    添加标签和分类，帮助大家更容易发现此智能体。
                  </Text>
                </Section>
              </Section>
            </Tabs.Content>
          </Tabs>
        </Card>
      </Modal.Body>

      <Modal.Footer>
        <BasicModalFooter
          left={
            agentId ? (
              <Button
                prominence="secondary"
                icon={SvgLink}
                onClick={handleCopyLink}
              >
                复制链接
              </Button>
            ) : undefined
          }
          cancel={
            <Button
              disabled={isSubmitting}
              prominence="secondary"
              onClick={handleClose}
            >
              取消
            </Button>
          }
          submit={
            <Button
              disabled={!dirty || isSubmitting}
              onClick={() => handleSubmit()}
            >
              保存
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
  ) => Promise<void> | void;
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

  const initialValues = useMemo(
    (): ShareAgentFormValues => ({
      selectedUserIds: userIds,
      selectedGroupIds: groupIds,
      isPublic: isPublic,
      isFeatured: isFeatured,
      labelIds: labelIds,
    }),
    [userIds, groupIds, isPublic, isFeatured, labelIds]
  );
  const [modalInitialValues, setModalInitialValues] =
    useState<ShareAgentFormValues>(initialValues);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    // Capture fresh props exactly when the modal opens, then keep them stable
    // while open so in-flight parent updates don't reset form state.
    if (shareAgentModal.isOpen && !wasOpenRef.current) {
      setModalInitialValues(initialValues);
    }
    wasOpenRef.current = shareAgentModal.isOpen;
  }, [shareAgentModal.isOpen, initialValues]);

  async function handleSubmit(values: ShareAgentFormValues) {
    await onShare?.(
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
        initialValues={modalInitialValues}
        onSubmit={handleSubmit}
        enableReinitialize
      >
        <ShareAgentFormContent agentId={agentId} />
      </Formik>
    </Modal>
  );
}
