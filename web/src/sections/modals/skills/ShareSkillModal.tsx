"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { RichStr } from "@opal/types";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import useShareableUsers from "@/hooks/useShareableUsers";
import { Content, Section, toast } from "@opal/layouts";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
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
import {
  updateSkillShares,
  transferSkillOwnership,
  resetSkillMarketplaceAccess,
} from "@/lib/skills/api";
import { canReadSkillHistory, canShareSkill } from "@/lib/skills/permissions";
import { useInstallationPolicyOptions } from "@/lib/skills/hooks";
import type {
  CustomSkill,
  SkillEditableDetail,
  SkillSharePermission,
  SkillInstallationPolicy,
} from "@/lib/skills/types";
import {
  serializeSkillSharing,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import type { MinimalUserSnapshot } from "@/lib/types";
import { Button, Card, SelectCard, Tabs, Text } from "@opal/components";
import {
  SvgArrowExchange,
  SvgArrowLeft,
  SvgBlocks,
  SvgUser,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import { SkillPreviewDetails } from "@/sections/modals/SkillPreviewModal";

import SkillVersions from "@/sections/skills/SkillVersions";
import useScreenSize from "@opal/hooks/useScreenSize";

type ShareModalView = "share" | "transfer" | "reset";

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
      initialTab?: "details" | "sharing";
      fallbackTitle?: string | RichStr;
      onSaved: () => void;
      onRestored?: (skill: SkillEditableDetail) => void;
      restoreDisabled?: boolean;
    }
);

export default function ShareSkillModal(props: ShareSkillModalProps) {
  const { open, onClose } = props;
  const { isSmallScreen } = useScreenSize();
  const initialTab =
    props.mode === "edit" ? (props.initialTab ?? "sharing") : "sharing";
  const [tab, setTab] = useState<"details" | "sharing" | "versions">(
    initialTab
  );
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
  const permissionOptions = useSharePermissionOptions();
  const scopeOptions = useShareScopeOptions();
  const installationOptions = useInstallationPolicyOptions();
  const { data: shareableUsersData } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: transferableUsersData } = useShareableUsers({
    includeApiKeys: false,
  });
  const { data: shareableGroupsData } = useShareableGroups();
  const { user: currentUser } = useUser();
  const { isGlobalHolder: canManageCompanySkills } = usePermissionAuthority(
    Permission.MANAGE_SKILLS
  );

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
  const previousView = useRef(view);
  const sourceStatus = useRef<HTMLDivElement>(null);
  const focusResetDescription = useCallback((node: HTMLElement | null) => {
    node?.focus();
  }, []);
  useEffect(() => {
    if (previousView.current === "reset" && view === "share") {
      sourceStatus.current?.focus();
    }
    previousView.current = view;
  }, [view]);
  const [installationPolicy, setInstallationPolicy] =
    useState<SkillInstallationPolicy>("AVAILABLE");
  const [initialPolicy, setInitialPolicy] =
    useState<SkillInstallationPolicy>("AVAILABLE");
  const [showIndividualAccess, setShowIndividualAccess] = useState(false);
  const [sharingSaving, setSaving] = useState(false);
  const [versionSaving, setVersionSaving] = useState(false);
  const saving = sharingSaving || versionSaving;
  const [resetError, setResetError] = useState<string | null>(null);
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
      setResetError(null);
      return;
    }
    if (!skill || hydrated || (skillId && isValidating)) return;
    const nextState: SkillShareDraftState = {
      groupShares: skill.group_shares,
      isPublic: skill.public_permission !== null,
      publicPermission: skill.public_permission ?? "VIEWER",
      userShares: skill.user_shares,
    };
    setInstallationPolicy(skill.installation_policy);
    setInitialPolicy(skill.installation_policy);
    setDraftState(nextState);
    setInitialState(nextState);
    setStagedUsers([]);
    setStagedGroups([]);
    setStagedPermission("VIEWER");
    setTransferTarget(null);
    setView("share");
    setHydrated(true);
  }, [open, skill, hydrated, skillId, isValidating, initialTab]);

  const effectiveState = useMemo(() => {
    if (!draftState) return null;
    return applyStagedShares(
      draftState,
      stagedUsers,
      stagedGroups,
      stagedPermission
    );
  }, [draftState, stagedGroups, stagedPermission, stagedUsers]);

  const marketplace = props.mode === "edit" ? loadedSkill?.marketplace : null;
  const isPersonalOwner =
    marketplace?.personal && skill?.user_permission === "OWNER";
  const canEditShares =
    props.mode === "edit"
      ? !!loadedSkill && canShareSkill({ skill: loadedSkill })
      : skill?.user_permission === "OWNER" ||
        skill?.user_permission === "EDITOR";
  const canEditAudience =
    canEditShares && (!marketplace?.personal || isPersonalOwner);
  const canEditUsers =
    canEditAudience &&
    (props.mode === "create" || !!skill?.owner || canManageCompanySkills);
  const canEditOrgVisibility =
    !skill?.external_app &&
    canEditAudience &&
    (canManageCompanySkills || isPersonalOwner);
  const canReset =
    !!marketplace &&
    !marketplace.personal &&
    !marketplace.follows_access &&
    canManageCompanySkills &&
    canEditShares;
  const canTransfer =
    props.mode === "edit" &&
    !marketplace &&
    !loadedSkill?.retired_at &&
    !!skill &&
    (skill.user_permission === "OWNER" ||
      (canManageCompanySkills && skill.ownership_vacant));
  const isDirty =
    !!effectiveState &&
    !!initialState &&
    (serializeDraftState(effectiveState) !==
      serializeDraftState(initialState) ||
      installationPolicy !== initialPolicy);

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
    if (!skill || !effectiveState || loadError || !canEditShares || saving)
      return;
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
      const payload = serializeSkillSharing(nextDraft, canManageCompanySkills, {
        canEditPublicAccess: !!canEditOrgVisibility,
      });
      await updateSkillShares(props.skillId, payload);
      void refreshSkill();
      toast.success(t("share.savedToast.message"));
      props.onSaved();
      closeModal();
    } catch (err) {
      console.error("Failed to update skill sharing", err);
      toast.error(
        err instanceof Error ? err.message : t("share.saveErrorToast.message")
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleTransfer() {
    if (
      !canTransfer ||
      saving ||
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

  async function handleReset() {
    if (props.mode !== "edit" || !canReset || saving || loadError) return;
    setSaving(true);
    setResetError(null);
    try {
      const saved = await resetSkillMarketplaceAccess(props.skillId);
      await refreshSkill(saved, { revalidate: false });
      setHydrated(false);
      setView("share");
      props.onSaved();
      toast.success(t("share.marketplace.resetSuccess"));
    } catch (error) {
      setResetError(
        error instanceof Error
          ? error.message
          : t("share.marketplace.resetError")
      );
    } finally {
      setSaving(false);
    }
  }

  function renderSharingContent() {
    if (!skill || !draftState || !effectiveState) return null;

    return (
      <Section gap={6} height="auto" alignItems="stretch">
        {marketplace && (
          <Card border="solid" padding={3}>
            <Section
              ref={sourceStatus}
              tabIndex={-1}
              gap={3}
              height="auto"
              alignItems="start"
            >
              <Content
                font="main-ui-action"
                title={t(
                  `share.marketplace.${marketplace.personal ? "personal" : marketplace.follows_access ? "following" : "overridden"}`
                )}
                description={t(
                  `share.marketplace.${marketplace.personal ? "personalDescription" : marketplace.follows_access ? "followingDescription" : "overriddenDescription"}`,
                  { name: marketplace.name }
                )}
              />
              {canReset && (
                <Button
                  prominence="secondary"
                  disabled={saving}
                  onClick={() => {
                    setResetError(null);
                    setView("reset");
                  }}
                >
                  {t("share.marketplace.reset")}
                </Button>
              )}
            </Section>
          </Card>
        )}
        <Section gap={3} height="auto" alignItems="stretch">
          <Content font="main-ui-action" title={t("share.accessTitle")} />
          <Card border="solid" padding={2}>
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
                disabled={!canEditOrgVisibility || saving}
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
              <SharePermissionMenu
                ariaLabel={t("share.organizationPermissionMenu.ariaLabel")}
                disabled={!canEditOrgVisibility || saving}
                onChange={(permission) => {
                  setDraftState((currentDraftState) =>
                    currentDraftState
                      ? { ...currentDraftState, publicPermission: permission }
                      : currentDraftState
                  );
                }}
                options={permissionOptions}
                value={effectiveState.publicPermission}
              />
            </Section>
          </Card>
          {skill.external_app && (
            <Text color="text-03" font="secondary-body">
              {t("share.externalAppNotice", {
                appName: skill.external_app.name,
              })}
            </Text>
          )}
        </Section>

        {canManageCompanySkills && (
          <Section gap={3} height="auto" alignItems="stretch">
            <Content
              font="main-ui-action"
              title={t("share.installation.title")}
              description={t("share.installation.description")}
            />
            <Section
              role="group"
              flexDirection="row"
              aria-label={t("share.installation.title")}
              gap={2}
              wrap
              height="auto"
              alignItems="stretch"
            >
              {installationOptions.map((option) => (
                <Section
                  key={option.value}
                  height="full"
                  className="min-w-0 grow basis-32"
                >
                  <SelectCard
                    role="button"
                    aria-label={option.label}
                    aria-pressed={installationPolicy === option.value}
                    state={
                      installationPolicy === option.value ? "selected" : "empty"
                    }
                    disabled={saving || !canEditShares}
                    onClick={() => setInstallationPolicy(option.value)}
                    padding={2}
                    rounding={3}
                  >
                    <Section flexDirection="row" gap={2} height="auto">
                      <option.icon
                        size={18}
                        aria-hidden
                        className="shrink-0 stroke-text-03"
                      />
                      <Text font="main-ui-action">{option.label}</Text>
                    </Section>
                  </SelectCard>
                </Section>
              ))}
            </Section>
            <Text color="text-03" font="secondary-body" role="status">
              {
                installationOptions.find(
                  (option) => option.value === installationPolicy
                )?.description
              }
            </Text>
          </Section>
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
            {canEditAudience ? (
              <AddPeoplePicker
                disabled={saving}
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
                users={canEditUsers ? (shareableUsersData ?? []) : []}
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
                            disabled={!canEditUsers || saving}
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
                          disabled={!canEditAudience || saving}
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
                  canTransfer && !saving ? (
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
                  canTransfer && !saving ? (
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

  const header = (
    <Modal.Header
      padding={isSmallScreen ? 0 : 2}
      reserveCloseSpace={isSmallScreen}
      icon={
        isSmallScreen
          ? undefined
          : view === "transfer"
            ? SvgArrowExchange
            : SvgBlocks
      }
      title={
        view === "reset"
          ? t("share.marketplace.reset")
          : !skill
            ? props.mode === "edit"
              ? (props.fallbackTitle ?? t("preview.fallbackTitle"))
              : t("share.accessTitle")
            : view === "transfer"
              ? markdown(t("share.header.transferTitle", { name: skill.name }))
              : skill.name
      }
      description={
        view !== "share" || (props.mode === "edit" && tab === "versions")
          ? undefined
          : props.mode === "edit"
            ? loadedSkill?.description
            : t("share.description")
      }
      gap={1}
      onClose={saving ? undefined : closeModal}
    />
  );

  return (
    <Modal
      open={open}
      onOpenChange={(isOpen) => !isOpen && !saving && closeModal()}
    >
      <Modal.Content
        restoreOpeningFocus
        height={props.mode === "edit" && view === "share" ? "lg" : "fit"}
        width={view === "share" ? "lg" : "sm"}
        maxHeight="80dvh"
      >
        {!isSmallScreen && header}
        <Modal.Body
          twoTone={false}
          alignItems="stretch"
          padding={isSmallScreen ? 2 : 4}
        >
          {isSmallScreen && header}
          {loadError ? (
            <Text>{skillCopy("editor.loadError.description")}</Text>
          ) : !skill || !draftState ? (
            <Text>{t("share.loading.message")}</Text>
          ) : view === "reset" ? (
            <Section gap={3} height="auto" alignItems="stretch">
              <Text ref={focusResetDescription} tabIndex={-1}>
                {t("share.marketplace.resetDescription", {
                  name: marketplace?.name ?? "",
                })}
              </Text>
              {resetError && (
                <Text color="status-error-05" role="alert">
                  {resetError}
                </Text>
              )}
            </Section>
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
              variant="underline"
              gap={isSmallScreen ? 3 : 6}
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
              <Tabs.List enableScrollArrows>
                <Tabs.Trigger value="details" disabled={saving}>
                  {t("tabs.details")}
                </Tabs.Trigger>
                <Tabs.Trigger value="sharing" disabled={saving}>
                  {t("tabs.sharing")}
                </Tabs.Trigger>
                {loadedSkill && canReadSkillHistory(loadedSkill) && (
                  <Tabs.Trigger value="versions" disabled={saving}>
                    {skillCopy("versions.title")}
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
              {loadedSkill && canReadSkillHistory(loadedSkill) && (
                <Tabs.Content value="versions">
                  <SkillVersions
                    skill={loadedSkill}
                    onBusyChange={setVersionSaving}
                    restoreDisabled={props.restoreDisabled}
                    onRestored={(restored) => {
                      props.onRestored?.(restored);
                      props.onSaved();
                    }}
                  />
                </Tabs.Content>
              )}
              <Tabs.Content
                value="sharing"
                keepMounted
                hidden={tab !== "sharing"}
              >
                {renderSharingContent()}
              </Tabs.Content>
            </Tabs>
          ) : (
            renderSharingContent()
          )}
        </Modal.Body>
        <Modal.Footer justifyContent="between" padding={isSmallScreen ? 2 : 4}>
          {view !== "share" ? (
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
              {view !== "share" ||
              (canEditShares && (tab === "sharing" || isDirty))
                ? t("share.cancelButton.label")
                : props.mode === "edit" && tab === "details"
                  ? t("preview.closeButton.label")
                  : t("share.doneButton.label")}
            </Button>
            {view === "reset" ? (
              <Button
                disabled={!canReset || saving || !!loadError}
                onClick={handleReset}
              >
                {t("share.marketplace.confirmReset")}
              </Button>
            ) : view === "transfer" ? (
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
                disabled={!isDirty || saving || !!loadError}
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
