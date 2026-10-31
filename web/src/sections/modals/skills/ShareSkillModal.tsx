"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
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
  SkillSharePermission,
  SkillInstallationPolicy,
} from "@/lib/skills/types";
import {
  serializeSkillSharing,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import type { MinimalUserSnapshot } from "@/lib/types";
import { Button, Card, SelectCard, Text } from "@opal/components";
import {
  SvgArrowExchange,
  SvgArrowLeft,
  SvgLock,
  SvgOrganization,
  SvgBlocks,
  SvgUser,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import { markdown } from "@opal/utils";

type ShareModalView = "share" | "transfer";

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
      onSaved: () => void;
    }
);

export default function ShareSkillModal(props: ShareSkillModalProps) {
  const { open, onClose } = props;
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
  const permissionOptions = useSharePermissionOptions({
    VIEWER: t("share.permissionMenu.canUse"),
    EDITOR: t("share.permissionMenu.canEdit"),
  });
  const scopeOptions = useShareScopeOptions();
  const { data: shareableUsersData } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: transferableUsersData } = useShareableUsers({
    includeApiKeys: false,
  });
  const { data: shareableGroupsData } = useShareableGroups();
  const { isAdmin, user: currentUser } = useUser();

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
    useState<SkillInstallationPolicy>("AVAILABLE");
  const [initialPolicy, setInitialPolicy] =
    useState<SkillInstallationPolicy>("AVAILABLE");
  const [showIndividualAccess, setShowIndividualAccess] = useState(false);
  const [saving, setSaving] = useState(false);
  const [hydrated, setHydrated] = useState(false);

  // Hydrate once per open session: a background SWR refresh of `skill` must
  // not wipe in-progress staged edits.
  useEffect(() => {
    if (!open) {
      setShowIndividualAccess(false);
      setHydrated(false);
      setDraftState(null);
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
  }, [open, skill, hydrated, skillId, isValidating]);

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
    !skill?.external_app &&
    (skill?.user_permission === "OWNER" ||
      (isAdmin && skill?.user_permission === "EDITOR"));
  const canTransfer =
    props.mode === "edit" &&
    !!skill &&
    (skill.user_permission === "OWNER" || (isAdmin && skill.ownership_vacant));
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
      const payload = serializeSkillSharing(nextDraft, isAdmin);
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
          <Content
            title={t("share.accessTitle")}
            sizePreset="main-ui"
            variant="section"
          />
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
              <SharePermissionMenu
                ariaLabel={t("share.organizationPermissionMenu.ariaLabel")}
                disabled={!canEditOrgVisibility}
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

        {isAdmin && (
          <Section gap={3} height="auto" alignItems="stretch">
            <Content
              title={t("share.installation.title")}
              description={t("share.installation.description")}
              sizePreset="main-ui"
              variant="section"
            />
            <Section
              role="group"
              flexDirection="row"
              aria-label={t("share.installation.title")}
              gap={2}
              height="auto"
              alignItems="stretch"
            >
              {(
                [
                  {
                    value: "AVAILABLE",
                    label: "available",
                    icon: SvgUser,
                  },
                  {
                    value: "DEFAULT",
                    label: "default",
                    icon: SvgOrganization,
                  },
                  {
                    value: "REQUIRED",
                    label: "required",
                    icon: SvgLock,
                  },
                ] as const
              ).map((option) => (
                <Section key={option.value} height="full" className="min-w-0">
                  <SelectCard
                    role="button"
                    aria-label={t(`share.installation.${option.label}`)}
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
                      <Text font="main-ui-action">
                        {t(`share.installation.${option.label}`)}
                      </Text>
                    </Section>
                  </SelectCard>
                </Section>
              ))}
            </Section>
            <Text color="text-03" font="secondary-body" role="status">
              {t(
                `share.installation.${
                  (
                    {
                      AVAILABLE: "availableDescription",
                      DEFAULT: "defaultDescription",
                      REQUIRED: "requiredDescription",
                    } as const
                  )[installationPolicy]
                }`
              )}
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
              title={t(
                effectiveState.isPublic
                  ? "share.individualAccessTitle"
                  : "share.peopleTitle"
              )}
              sizePreset="main-ui"
              variant="section"
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
          <Content
            title={t("share.ownershipTitle")}
            sizePreset="main-ui"
            variant="section"
          />
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
        height="fit"
        width={view === "transfer" ? "sm" : "lg"}
        maxHeight="80dvh"
        position="top"
      >
        <Modal.Header
          icon={view === "transfer" ? SvgArrowExchange : SvgBlocks}
          title={
            !skill
              ? t("share.accessTitle")
              : view === "transfer"
                ? markdown(
                    t("share.header.transferTitle", { name: skill.name })
                  )
                : skill.name
          }
          description={view === "transfer" ? undefined : t("share.description")}
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
              {canEditShares || view === "transfer"
                ? t("share.cancelButton.label")
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
            ) : canEditShares ? (
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
