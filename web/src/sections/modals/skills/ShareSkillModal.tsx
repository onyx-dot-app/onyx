"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { RichStr } from "@opal/types";
import { useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import useShareableUsers from "@/hooks/useShareableUsers";
import { Content, Section, toast } from "@opal/layouts";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Modal } from "@opal/components";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import { SharePermissionMenu } from "@/lib/permissions/components";
import {
  useSharePermissionOptions,
  useShareScopeOptions,
} from "@/sections/modals/shareAccessConstants";
import {
  applyStagedShares,
  serializeDraftState,
  type ShareDraftState as BaseShareDraftState,
} from "@/sections/modals/shareDraftState";
import {
  TransferOwnershipTarget,
  TransferOwnershipView,
} from "@/sections/modals/TransferOwnershipView";
import {
  StaticPermissionLabel,
  TransferTrailingButton,
} from "@/sections/modals/ShareModalPermissionControls";
import { updateSkillShares, transferSkillOwnership } from "@/lib/skills/api";
import type {
  CustomSkill,
  SkillEditableDetail,
  SkillSharePermission,
  SkillInstallationPolicy,
} from "@/lib/skills/types";
import {
  canChangeOrganizationAccess,
  groupSettingChanges,
  serializeSkillSharing,
  type GroupAccessRow,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import {
  INHERIT,
  fromPolicyChoice,
  isPolicyChoice,
  toPolicyChoice,
  useCompanyPolicyOptions,
  useInstallationPolicyCopy,
} from "@/lib/skills/installationPolicy";
import SkillGroupAccess from "@/sections/modals/skills/SkillGroupAccess";
import { Permission, type MinimalUserSnapshot } from "@/lib/types";
import {
  Button,
  Card,
  InputSingleSelect,
  MessageCard,
  Tabs,
  Text,
} from "@opal/components";
import {
  SvgArrowExchange,
  SvgArrowLeft,
  SvgBubbleText,
  SvgOrganization,
  SvgBlocks,
  SvgUser,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import { SkillPreviewDetails } from "@/sections/modals/SkillPreviewModal";
import { usePublishAction } from "@/lib/skills/hooks";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import { useSkillLimitCopy } from "@/lib/skills/limits";

type ShareModalView = "share" | "transfer";

type SkillDialogTab = "details" | "sharing" | "versions";

type SkillShareDraftState = BaseShareDraftState<SkillSharePermission>;

type ShareSkillModalProps = {
  open: boolean;
  onClose: () => void;
} & (
  | {
      mode: "create";
      draft: SkillSharingDraft;
      onSaveDraft: (draft: SkillSharingDraft) => void;
    }
  | {
      mode: "edit";
      skillId: string;
      initialTab?: SkillDialogTab;
      fallbackTitle?: string | RichStr;
      onSaved: () => void;
      /** Lets an open editor take the fields of a restored version. */
      onVersionRestored?: (restored: SkillEditableDetail) => void;
      /** The open editor has unsaved changes, so Restore is off. */
      restoreBlocked?: boolean;
    }
);

export default function ShareSkillModal(props: ShareSkillModalProps) {
  const { open, onClose } = props;
  const initialTab =
    props.mode === "edit" ? (props.initialTab ?? "sharing") : "sharing";
  const [tab, setTab] = useState<SkillDialogTab>(initialTab);
  const [detailsVisited, setDetailsVisited] = useState(
    initialTab === "details"
  );
  const skillId = props.mode === "edit" ? props.skillId : null;
  const {
    data: loadedSkill,
    error: loadError,
    isValidating,
    mutate: refreshSkill,
  } = useSWR<CustomSkill>(
    open && skillId ? SWR_KEYS.skillSharing(skillId) : null,
    errorHandlingFetcher
  );
  const skill = props.mode === "create" ? props.draft : loadedSkill;
  const t = useTranslations("skills.modals");
  const skillCopy = useTranslations("skills");
  const { describeError } = useSkillLimitCopy();
  const permissionOptions = useSharePermissionOptions();
  const scopeOptions = useShareScopeOptions();
  const { data: shareableUsersData } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: transferableUsersData } = useShareableUsers({
    includeApiKeys: false,
  });
  const { data: shareableGroupsData } = useShareableGroups();
  const { isAdmin, user: currentUser } = useUser();
  const {
    isGlobalHolder: isOrganizationManager,
    isScopedManager: isScopedPluginManager,
  } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const policyCopy = useInstallationPolicyCopy();
  const policyCopyT = useTranslations("skills.installationPolicy");
  const companyOptions = useCompanyPolicyOptions(
    loadedSkill?.default_installation_policy ?? null
  );
  const { mutate } = useSWRConfig();
  const publishAction = usePublishAction();

  const [draftState, setDraftState] = useState<SkillShareDraftState | null>(
    null
  );
  const [initialState, setInitialState] = useState<SkillShareDraftState | null>(
    null
  );
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [stagedPermission, setStagedPermission] =
    useState<SkillSharePermission>("VIEWER");
  const [transferTarget, setTransferTarget] =
    useState<TransferOwnershipTarget>(null);
  const [view, setView] = useState<ShareModalView>("share");
  const [installationPolicy, setInstallationPolicy] =
    useState<SkillInstallationPolicy | null>(null);
  const [initialPolicy, setInitialPolicy] =
    useState<SkillInstallationPolicy | null>(null);
  const [groupRows, setGroupRows] = useState<GroupAccessRow[]>([]);
  const [initialGroupRows, setInitialGroupRows] = useState<GroupAccessRow[]>(
    []
  );
  const [showIndividualAccess, setShowIndividualAccess] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate once per open session: a background SWR refresh of `skill` must
  // not wipe in-progress staged edits.
  useEffect(() => {
    if (!open) {
      setShowIndividualAccess(false);
      setHydrated(false);
      setTab(initialTab);
      setDetailsVisited(initialTab === "details");
      setDraftState(null);
      return;
    }
    if (!skill || hydrated || (skillId && isValidating)) return;
    const nextState: SkillShareDraftState = {
      groupShares: skill.group_shares,
      isPublic: skill.public_permission !== null,
      // The organization can only view; editors are named users and groups.
      publicPermission: "VIEWER",
      userShares: skill.user_shares,
    };
    setInstallationPolicy(skill.installation_policy);
    setInitialPolicy(skill.installation_policy);
    const nextGroupRows: GroupAccessRow[] = (
      loadedSkill?.group_summaries ?? []
    ).map((summary) => ({
      group_id: summary.group_id,
      group_name: summary.group_name,
      permission: summary.permission,
      choice: toPolicyChoice(summary.installation_policy),
    }));
    setGroupRows(nextGroupRows);
    setInitialGroupRows(nextGroupRows);
    setDraftState(nextState);
    setInitialState(nextState);
    setStagedUsers([]);
    setStagedGroups([]);
    setStagedPermission("VIEWER");
    setTransferTarget(null);
    setView("share");
    setHydrated(true);
  }, [open, skill, loadedSkill, hydrated, skillId, isValidating, initialTab]);

  const effectiveState = useMemo(() => {
    if (!draftState) return null;
    return applyStagedShares(
      draftState,
      stagedUsers,
      stagedGroups,
      stagedPermission
    );
  }, [draftState, stagedGroups, stagedPermission, stagedUsers]);

  const canEditShares =
    skill?.user_permission === "OWNER" || skill?.user_permission === "EDITOR";
  const canEditOrgVisibility =
    !!skill &&
    !skill.external_app &&
    canChangeOrganizationAccess(skill, isOrganizationManager);
  // Publishing is one-way: a saved published skill shows no private option.
  const isPublished = props.mode === "edit" && initialState?.isPublic === true;
  const isPublishing = !!effectiveState?.isPublic && !isPublished;
  // Group settings need manage-plugins: organization-wide, or for the
  // manager's groups on a skill that is not published.
  const canSetGroupSettings =
    props.mode === "edit" &&
    (isOrganizationManager ||
      (isScopedPluginManager && !isPublished && !isPublishing));
  const groupChanges = useMemo(
    () => groupSettingChanges(initialGroupRows, groupRows),
    [initialGroupRows, groupRows]
  );
  const viewerLabel = permissionOptions.find(
    (option) => option.value === "VIEWER"
  )?.label;
  const canTransfer =
    props.mode === "edit" &&
    !!skill &&
    (skill.user_permission === "OWNER" || (isAdmin && skill.ownership_vacant));
  const isDirty =
    !!effectiveState &&
    !!initialState &&
    (serializeDraftState(effectiveState) !==
      serializeDraftState(initialState) ||
      installationPolicy !== initialPolicy ||
      groupChanges.length > 0);

  const existingUserIds = useMemo(() => {
    const ids = new Set(draftState?.userShares.map((share) => share.user.id));
    if (skill?.owner?.id) ids.add(skill.owner.id);
    return ids;
  }, [draftState?.userShares, skill?.owner?.id]);
  const existingGroupIds = useMemo(
    () => new Set(draftState?.groupShares.map((share) => share.group_id)),
    [draftState?.groupShares]
  );

  const closeModal = useCallback(() => {
    setView("share");
    onClose();
  }, [onClose]);

  const updateUserSharePermission = useCallback(
    (userId: string, permission: SkillSharePermission) => {
      const stagedUser = stagedUsers.find((user) => user.id === userId);
      if (stagedUser) {
        setStagedUsers((currentUsers) =>
          currentUsers.filter((user) => user.id !== userId)
        );
        setDraftState((currentDraftState) =>
          currentDraftState
            ? {
                ...currentDraftState,
                userShares: [
                  ...currentDraftState.userShares.filter(
                    (share) => share.user.id !== userId
                  ),
                  { permission, user: stagedUser },
                ],
              }
            : currentDraftState
        );
        return;
      }
      setDraftState((currentDraftState) =>
        currentDraftState
          ? {
              ...currentDraftState,
              userShares: currentDraftState.userShares.map((share) =>
                share.user.id === userId ? { ...share, permission } : share
              ),
            }
          : currentDraftState
      );
    },
    [stagedUsers]
  );

  const updateGroupSharePermission = useCallback(
    (groupId: number, permission: SkillSharePermission) => {
      const stagedGroup = stagedGroups.find((group) => group.id === groupId);
      if (stagedGroup) {
        setStagedGroups((currentGroups) =>
          currentGroups.filter((group) => group.id !== groupId)
        );
        setDraftState((currentDraftState) =>
          currentDraftState
            ? {
                ...currentDraftState,
                groupShares: [
                  ...currentDraftState.groupShares.filter(
                    (share) => share.group_id !== groupId
                  ),
                  {
                    group_id: stagedGroup.id,
                    group_name: stagedGroup.name,
                    permission,
                  },
                ],
              }
            : currentDraftState
        );
        return;
      }
      setDraftState((currentDraftState) =>
        currentDraftState
          ? {
              ...currentDraftState,
              groupShares: currentDraftState.groupShares.map((share) =>
                share.group_id === groupId ? { ...share, permission } : share
              ),
            }
          : currentDraftState
      );
    },
    [stagedGroups]
  );

  const removeUserShare = useCallback((userId: string) => {
    setStagedUsers((currentUsers) =>
      currentUsers.filter((user) => user.id !== userId)
    );
    setDraftState((currentDraftState) =>
      currentDraftState
        ? {
            ...currentDraftState,
            userShares: currentDraftState.userShares.filter(
              (share) => share.user.id !== userId
            ),
          }
        : currentDraftState
    );
  }, []);

  const removeGroupShare = useCallback((groupId: number) => {
    setStagedGroups((currentGroups) =>
      currentGroups.filter((group) => group.id !== groupId)
    );
    setDraftState((currentDraftState) =>
      currentDraftState
        ? {
            ...currentDraftState,
            groupShares: currentDraftState.groupShares.filter(
              (share) => share.group_id !== groupId
            ),
          }
        : currentDraftState
    );
  }, []);

  async function handleSave() {
    if (!skill || !effectiveState || loadError) return;
    if (!isDirty) {
      closeModal();
      return;
    }

    setSaving(true);
    try {
      const nextDraft: SkillSharingDraft = {
        ...skill,
        user_shares: effectiveState.userShares,
        group_shares: effectiveState.groupShares,
        public_permission: effectiveState.isPublic
          ? effectiveState.publicPermission
          : null,
        installation_policy: installationPolicy,
      };
      if (props.mode === "create") {
        props.onSaveDraft(nextDraft);
        closeModal();
        return;
      }
      const payload = serializeSkillSharing(
        nextDraft,
        isAdmin,
        isOrganizationManager,
        initialPolicy
      );
      if (canSetGroupSettings && groupChanges.length > 0) {
        payload.group_settings = groupChanges;
      }
      const saved = await updateSkillShares(props.skillId, payload);
      void refreshSkill();
      if (
        isPublishing &&
        saved.public_permission === null &&
        saved.pending_version_number !== null
      ) {
        toast.info(t("share.reviewRequestedToast.message"));
      } else {
        toast.success(t("share.savedToast.message"));
      }
      props.onSaved();
      closeModal();
    } catch (err) {
      console.error("Failed to update skill sharing", err);
      toast.error(describeError(err, t("share.saveErrorToast.message")));
    } finally {
      setSaving(false);
    }
  }

  function handleVersionsChanged() {
    if (props.mode !== "edit") return;
    void refreshSkill();
    void mutate(SWR_KEYS.userSkillPreview(props.skillId));
    props.onSaved();
  }

  async function handleTransfer() {
    if (
      props.mode !== "edit" ||
      !skill ||
      !transferTarget ||
      transferTarget.type !== "user"
    )
      return;

    setSaving(true);
    try {
      await transferSkillOwnership(props.skillId, {
        new_owner_user_id: transferTarget.value.replace("user-", ""),
      });
      toast.success(t("share.transferredToast.message"));
      props.onSaved();
      closeModal();
    } catch (err) {
      console.error("Failed to transfer skill ownership", err);
      toast.error(
        err instanceof Error
          ? err.message
          : t("share.transferErrorToast.message")
      );
    } finally {
      setSaving(false);
    }
  }

  function renderSharingContent() {
    if (!skill || !draftState || !effectiveState) return null;

    return (
      <Section gap={6} height="auto" alignItems="stretch">
        <Section gap={3} height="auto" alignItems="stretch">
          <Content font="main-ui-action" title={t("share.accessTitle")} />
          <Card border="solid" padding={2}>
            {isPublished ? (
              <ShareAccessRow
                icon={SvgOrganization}
                title={t("share.published.title")}
                description={t("share.published.description")}
                rightChildren={
                  viewerLabel ? (
                    <StaticPermissionLabel
                      icon={SvgBubbleText}
                      label={viewerLabel}
                    />
                  ) : undefined
                }
              />
            ) : (
              <Section
                flexDirection="row"
                justifyContent="between"
                wrap
                gap={2}
                height="auto"
                padding={2}
              >
                <SharePermissionMenu
                  ariaLabel={t("share.scopeMenu.ariaLabel")}
                  disabled={!canEditOrgVisibility}
                  onChange={(scope) => {
                    setDraftState((currentDraftState) =>
                      currentDraftState
                        ? { ...currentDraftState, isPublic: scope === "PUBLIC" }
                        : currentDraftState
                    );
                  }}
                  options={scopeOptions}
                  showTriggerIcon
                  value={effectiveState.isPublic ? "PUBLIC" : "PRIVATE"}
                />
              </Section>
            )}
          </Card>
          {isPublishing && publishAction === "off" && (
            <MessageCard
              variant="error"
              outerPadding={1}
              innerPadding={1}
              title={t("share.publishOff.title")}
              description={t("share.publishOff.description")}
            />
          )}
          {isPublishing && publishAction !== "off" && (
            <MessageCard
              variant="warning"
              outerPadding={1}
              innerPadding={1}
              title={t("share.publishWarning.title")}
              description={t("share.publishWarning.description")}
            />
          )}
          {isPublishing && publishAction === "review" && (
            <MessageCard
              variant="info"
              outerPadding={1}
              innerPadding={1}
              title={t("share.publishReview.title")}
              description={t("share.publishReview.description")}
            />
          )}
          {skill.external_app && (
            <Text color="text-03" font="secondary-body">
              {t("share.externalAppNotice", {
                appName: skill.external_app.name,
              })}
            </Text>
          )}
        </Section>

        {isAdmin && (
          <Section gap={3} height="auto" alignItems="stretch">
            <Content
              font="main-ui-action"
              title={t("share.installation.title")}
              description={t("share.installation.description")}
            />
            <InputSingleSelect
              placeholder={t("share.installation.title")}
              value={toPolicyChoice(installationPolicy)}
              defaultOption={INHERIT}
              options={companyOptions}
              disabled={saving || !canEditShares}
              onValueChange={(value) => {
                if (isPolicyChoice(value))
                  setInstallationPolicy(fromPolicyChoice(value));
              }}
            />
            <Text color="text-03" font="secondary-body" role="status">
              {installationPolicy === null
                ? policyCopyT("inherit.organizationDescription")
                : policyCopy.description(installationPolicy)}
            </Text>
          </Section>
        )}

        {canSetGroupSettings && (
          <SkillGroupAccess
            rows={groupRows}
            company={
              installationPolicy ??
              loadedSkill?.default_installation_policy ??
              null
            }
            groups={shareableGroupsData ?? []}
            description={t("share.groupAccess.description")}
            disabled={saving}
            onChange={setGroupRows}
          />
        )}

        {effectiveState.isPublic && (
          <Section height="auto" alignItems="start">
            <Button
              prominence="secondary"
              aria-expanded={showIndividualAccess}
              onClick={() => setShowIndividualAccess((shown) => !shown)}
            >
              {t("share.manageIndividualAccess")}
            </Button>
          </Section>
        )}
        {(!effectiveState.isPublic || showIndividualAccess) && (
          <Section gap={3} height="auto" alignItems="stretch">
            <Content
              font="main-ui-action"
              title={t(
                effectiveState.isPublic
                  ? "share.individualAccessTitle"
                  : "share.peopleTitle"
              )}
            />
            {canEditShares ? (
              <AddPeoplePicker
                existingGroupIds={existingGroupIds}
                existingUserIds={existingUserIds}
                groups={shareableGroupsData ?? []}
                onAddGroup={(group) => {
                  setStagedGroups((currentGroups) => [...currentGroups, group]);
                }}
                onAddUser={(user) => {
                  setStagedUsers((currentUsers) => [...currentUsers, user]);
                }}
                onRemoveGroup={(groupId) => {
                  setStagedGroups((currentGroups) =>
                    currentGroups.filter((group) => group.id !== groupId)
                  );
                }}
                onRemoveUser={(userId) => {
                  setStagedUsers((currentUsers) =>
                    currentUsers.filter((user) => user.id !== userId)
                  );
                }}
                onStagedPermissionChange={setStagedPermission}
                stagedGroups={stagedGroups}
                stagedPermission={stagedPermission}
                stagedUsers={stagedUsers}
                users={shareableUsersData ?? []}
              />
            ) : null}
            {(effectiveState.userShares.length > 0 ||
              effectiveState.groupShares.length > 0) && (
              <Card border="solid" padding={2}>
                <Section gap={1} height="auto" alignItems="stretch">
                  {effectiveState.userShares.map((share) => {
                    const isCurrentUser = currentUser?.id === share.user.id;
                    return (
                      <ShareAccessRow
                        avatarInitial={share.user.email.charAt(0).toUpperCase()}
                        icon={SvgUser}
                        key={share.user.id}
                        rightChildren={
                          <SharePermissionMenu
                            ariaLabel={t("share.permissionMenu.ariaLabel", {
                              name: share.user.email,
                            })}
                            disabled={!canEditShares}
                            onChange={(permission) =>
                              updateUserSharePermission(
                                share.user.id,
                                permission
                              )
                            }
                            onRemove={() => removeUserShare(share.user.id)}
                            options={permissionOptions}
                            value={share.permission}
                          />
                        }
                        title={
                          isCurrentUser
                            ? t("share.currentUserLabel", {
                                email: share.user.email,
                              })
                            : share.user.email
                        }
                      />
                    );
                  })}

                  {effectiveState.groupShares.map((share) => (
                    <ShareAccessRow
                      avatarIcon={SvgUsers}
                      icon={SvgUsers}
                      key={share.group_id}
                      rightChildren={
                        <SharePermissionMenu
                          ariaLabel={t("share.permissionMenu.ariaLabel", {
                            name: share.group_name,
                          })}
                          disabled={!canEditShares}
                          onChange={(permission) =>
                            updateGroupSharePermission(
                              share.group_id,
                              permission
                            )
                          }
                          onRemove={() => removeGroupShare(share.group_id)}
                          options={permissionOptions}
                          value={share.permission}
                        />
                      }
                      title={share.group_name}
                    />
                  ))}
                </Section>
              </Card>
            )}
          </Section>
        )}
        <Section gap={3} height="auto" alignItems="stretch">
          <Content font="main-ui-action" title={t("share.ownershipTitle")} />
          <Card border="solid" padding={2}>
            {skill.owner ? (
              <ShareAccessRow
                avatarInitial={skill.owner.email.charAt(0).toUpperCase()}
                icon={SvgUser}
                rightChildren={
                  <StaticPermissionLabel
                    icon={SvgUserManage}
                    label={t("share.ownerLabel")}
                    muted={!canTransfer}
                  />
                }
                title={
                  currentUser && skill.owner.id === currentUser.id
                    ? t("share.currentUserLabel", {
                        email: skill.owner.email,
                      })
                    : skill.owner.email
                }
                trailing={
                  canTransfer ? (
                    <TransferTrailingButton
                      onTransfer={() => setView("transfer")}
                    />
                  ) : undefined
                }
              />
            ) : (
              <ShareAccessRow
                icon={SvgUserManage}
                rightChildren={
                  <StaticPermissionLabel
                    icon={SvgUserManage}
                    label={t("share.ownerLabel")}
                  />
                }
                title={t("share.noOwnerTitle")}
                trailing={
                  canTransfer ? (
                    <TransferTrailingButton
                      onTransfer={() => setView("transfer")}
                    />
                  ) : undefined
                }
              />
            )}
          </Card>
        </Section>
      </Section>
    );
  }

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && closeModal()}>
      <Modal.Content
        height={props.mode === "edit" && view !== "transfer" ? "lg" : "fit"}
        width={view === "transfer" ? "sm" : "lg"}
        maxHeight="80dvh"
      >
        <Modal.Header
          icon={view === "transfer" ? SvgArrowExchange : SvgBlocks}
          title={
            !skill
              ? props.mode === "edit"
                ? (props.fallbackTitle ?? t("preview.fallbackTitle"))
                : t("share.accessTitle")
              : view === "transfer"
                ? markdown(
                    t("share.header.transferTitle", { name: skill.name })
                  )
                : skill.name
          }
          description={
            view === "transfer"
              ? undefined
              : props.mode === "edit"
                ? loadedSkill?.description
                : t("share.description")
          }
          gap={1}
          onClose={closeModal}
        />
        <Modal.Body twoTone={false} alignItems="stretch">
          {loadError ? (
            <Text>{skillCopy("editor.loadError.description")}</Text>
          ) : !skill || !draftState ? (
            <Text>{t("share.loading.message")}</Text>
          ) : view === "transfer" ? (
            <TransferOwnershipView
              agent={{ owner: skill.owner, owner_group: null }}
              groups={[]}
              onSelectedTargetChange={setTransferTarget}
              selectedTarget={transferTarget}
              users={transferableUsersData ?? []}
            />
          ) : props.mode === "edit" ? (
            <Tabs
              value={tab}
              variant="contained"
              gap={6}
              onValueChange={(value) => {
                if (
                  saving ||
                  (value !== "details" &&
                    value !== "sharing" &&
                    value !== "versions")
                )
                  return;
                setTab(value);
                if (value === "details") setDetailsVisited(true);
              }}
            >
              <Tabs.List>
                <Tabs.Trigger value="details" disabled={saving}>
                  {t("tabs.details")}
                </Tabs.Trigger>
                <Tabs.Trigger value="sharing" disabled={saving}>
                  {t("tabs.sharing")}
                </Tabs.Trigger>
                {canEditShares && (
                  <Tabs.Trigger value="versions" disabled={saving}>
                    {t("tabs.versions")}
                  </Tabs.Trigger>
                )}
              </Tabs.List>
              <Tabs.Content
                value="details"
                keepMounted
                hidden={tab !== "details"}
              >
                {detailsVisited && (
                  <SkillPreviewDetails
                    skillId={props.skillId}
                    unavailableReason={loadedSkill?.unavailable_reason}
                  />
                )}
              </Tabs.Content>
              <Tabs.Content
                value="sharing"
                keepMounted
                hidden={tab !== "sharing"}
              >
                {renderSharingContent()}
              </Tabs.Content>
              {canEditShares && (
                <Tabs.Content value="versions">
                  {loadedSkill && (
                    <SkillVersionsTab
                      skill={loadedSkill}
                      canPublish={canChangeOrganizationAccess(
                        loadedSkill,
                        isOrganizationManager
                      )}
                      onChanged={handleVersionsChanged}
                      onRestored={props.onVersionRestored}
                      restoreBlocked={props.restoreBlocked}
                    />
                  )}
                </Tabs.Content>
              )}
            </Tabs>
          ) : (
            renderSharingContent()
          )}
        </Modal.Body>
        <Modal.Footer justifyContent="between">
          {view === "transfer" ? (
            <Button
              disabled={saving}
              icon={SvgArrowLeft}
              onClick={() => {
                setTransferTarget(null);
                setView("share");
              }}
              prominence="secondary"
            >
              {t("share.backButton.label")}
            </Button>
          ) : (
            <span aria-hidden />
          )}

          <Section flexDirection="row" gap={2} width="auto" height="auto">
            <Button
              disabled={saving}
              onClick={closeModal}
              prominence="secondary"
            >
              {view === "transfer" ||
              (canEditShares && (tab === "sharing" || isDirty))
                ? t("share.cancelButton.label")
                : props.mode === "edit" && tab !== "sharing"
                  ? t("preview.closeButton.label")
                  : t("share.doneButton.label")}
            </Button>
            {view === "transfer" ? (
              <Button
                disabled={
                  !transferTarget || transferTarget.type !== "user" || saving
                }
                onClick={handleTransfer}
              >
                {t("share.transferButton.label")}
              </Button>
            ) : canEditShares && (tab === "sharing" || isDirty) ? (
              <Button
                disabled={
                  !isDirty ||
                  saving ||
                  !!loadError ||
                  (isPublishing && publishAction === "off")
                }
                onClick={handleSave}
              >
                {t("share.saveButton.label")}
              </Button>
            ) : null}
          </Section>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
