"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Card, MessageCard, Modal, Text } from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgBlocks, SvgLock, SvgOrganization, SvgUsers } from "@opal/icons";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import useShareableUsers from "@/hooks/useShareableUsers";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import type { MinimalUserSnapshot } from "@/lib/types";
import type {
  SkillInstallationPolicy,
  SkillSharePermission,
} from "@/lib/skills/types";
import type { SkillShareUpdatePayload } from "@/lib/skills/api";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import {
  SharePermissionMenu,
  type SharePermissionMenuOption,
} from "@/lib/permissions/components";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import { useSharePermissionOptions } from "@/sections/modals/shareAccessConstants";
import { useInstallationPolicyOptions } from "@/lib/skills/hooks";

interface BulkSkillSharingModalProps {
  count: number;
  /** Selected company synced skills that still follow marketplace access. */
  followingMarketplaceCount?: number;
  canChangeOrgAccess: boolean;
  canChangeUserAccess: boolean;
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onSave: (sharing: SkillShareUpdatePayload) => Promise<void>;
}

type GroupPolicyChoice = SkillInstallationPolicy | "KEEP" | "INHERIT";

export default function BulkSkillSharingModal({
  count,
  followingMarketplaceCount = 0,
  canChangeOrgAccess,
  canChangeUserAccess,
  open,
  saving,
  onClose,
  onSave,
}: BulkSkillSharingModalProps) {
  const t = useTranslations("skills.bulk");
  const shareCopy = useTranslations("skills.modals.share");
  const {
    isGlobalHolder: canManageCompanySkills,
    isScopedManager: isScopedSkillManager,
  } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  // The server checks each skill's groups; this only hides controls that
  // cannot succeed for anyone without manage-skills.
  const canSetGroupPolicies = canManageCompanySkills || isScopedSkillManager;
  const { data: users } = useShareableUsers({ includeApiKeys: true });
  const { data: groups } = useShareableGroups();
  const [scope, setScope] = useState<"KEEP" | "PRIVATE" | "PUBLIC">("KEEP");
  const [policy, setPolicy] = useState<"KEEP" | SkillInstallationPolicy>(
    "KEEP"
  );
  const [permission, setPermission] = useState<SkillSharePermission>("VIEWER");
  const [publicPermission, setPublicPermission] =
    useState<SkillSharePermission>("VIEWER");
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [groupPolicies, setGroupPolicies] = useState<
    Map<number, GroupPolicyChoice>
  >(() => new Map());
  const permissionOptions = useSharePermissionOptions();
  const installationOptions = useInstallationPolicyOptions();
  const groupPolicyOptions: SharePermissionMenuOption<GroupPolicyChoice>[] = [
    { value: "KEEP", label: t("unchanged"), icon: SvgBlocks },
    {
      value: "INHERIT",
      label: shareCopy("groupInstallation.inherit"),
      description: shareCopy("groupInstallation.inheritDescription"),
      icon: SvgOrganization,
    },
    ...installationOptions,
  ];
  const canChangeCompanyAccess = canManageCompanySkills && canChangeOrgAccess;
  const effectiveScope = canChangeCompanyAccess ? scope : "KEEP";
  const changed =
    effectiveScope !== "KEEP" ||
    (canManageCompanySkills && policy !== "KEEP") ||
    (canChangeUserAccess && stagedUsers.length > 0) ||
    stagedGroups.length > 0;

  // The parent keeps this modal mounted, so a generic close (X, backdrop)
  // keeps the staged edits. Cancel and a submitted save discard them.
  function reset() {
    setScope("KEEP");
    setPolicy("KEEP");
    setPermission("VIEWER");
    setPublicPermission("VIEWER");
    setStagedUsers([]);
    setStagedGroups([]);
    setGroupPolicies(new Map());
  }

  async function save() {
    const sharing: SkillShareUpdatePayload = {};
    if (effectiveScope !== "KEEP")
      sharing.public_permission =
        effectiveScope === "PUBLIC" ? publicPermission : null;
    if (canManageCompanySkills && policy !== "KEEP")
      sharing.installation_policy = policy;
    if (canChangeUserAccess && stagedUsers.length)
      sharing.user_shares = stagedUsers.map((user) => ({
        user_id: user.id,
        permission,
      }));
    if (stagedGroups.length)
      sharing.group_shares = stagedGroups.map((group) => {
        const choice = canSetGroupPolicies
          ? (groupPolicies.get(group.id) ?? "KEEP")
          : "KEEP";
        // KEEP omits the setting so each skill keeps its own override.
        return choice === "KEEP"
          ? { group_id: group.id, permission }
          : {
              group_id: group.id,
              permission,
              installation_policy: choice === "INHERIT" ? null : choice,
            };
      });
    await onSave(sharing);
    reset();
  }

  return (
    <Modal
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen && !saving) onClose();
      }}
    >
      <Modal.Content width="md" height="fit">
        <Modal.Header
          icon={SvgBlocks}
          title={t("shareTitle", { count })}
          description={t("shareDescription")}
          onClose={() => {
            if (!saving) onClose();
          }}
        />
        <Modal.Body>
          <Section gap={4} height="auto" alignItems="stretch">
            <Section gap={2} height="auto" alignItems="stretch">
              <Content font="main-ui-action" title={shareCopy("accessTitle")} />
              <SharePermissionMenu
                value={effectiveScope}
                onChange={setScope}
                ariaLabel={shareCopy("accessTitle")}
                disabled={saving || !canChangeCompanyAccess}
                options={[
                  { value: "KEEP", label: t("unchanged"), icon: SvgUsers },
                  {
                    value: "PUBLIC",
                    label: t("everyone"),
                    icon: SvgOrganization,
                  },
                  { value: "PRIVATE", label: t("invitedOnly"), icon: SvgLock },
                ]}
              />
              {effectiveScope === "PUBLIC" && (
                <SharePermissionMenu
                  value={publicPermission}
                  onChange={setPublicPermission}
                  options={permissionOptions}
                  disabled={saving || !canChangeCompanyAccess}
                />
              )}
            </Section>
            {canManageCompanySkills && (
              <Section gap={2} height="auto" alignItems="stretch">
                <Content
                  font="main-ui-action"
                  title={shareCopy("installation.title")}
                />
                <SharePermissionMenu
                  value={policy}
                  onChange={setPolicy}
                  ariaLabel={shareCopy("installation.title")}
                  disabled={saving}
                  options={[
                    { value: "KEEP", label: t("unchanged"), icon: SvgBlocks },
                    ...installationOptions,
                  ]}
                />
              </Section>
            )}
            <Section gap={2} height="auto" alignItems="stretch">
              <Content font="main-ui-action" title={shareCopy("peopleTitle")} />
              <Text font="secondary-body" color="text-03">
                {t("addAccessDescription")}
              </Text>
              <AddPeoplePicker
                disabled={saving}
                existingUserIds={new Set()}
                existingGroupIds={new Set()}
                users={canChangeUserAccess ? (users ?? []) : []}
                groups={groups ?? []}
                stagedUsers={canChangeUserAccess ? stagedUsers : []}
                stagedGroups={stagedGroups}
                stagedPermission={permission}
                onStagedPermissionChange={setPermission}
                onAddUser={(user) =>
                  setStagedUsers((current) => [...current, user])
                }
                onAddGroup={(group) =>
                  setStagedGroups((current) => [...current, group])
                }
                onRemoveUser={(id) =>
                  setStagedUsers((current) =>
                    current.filter((user) => user.id !== id)
                  )
                }
                onRemoveGroup={(id) => {
                  setStagedGroups((current) =>
                    current.filter((group) => group.id !== id)
                  );
                  setGroupPolicies((current) => {
                    const next = new Map(current);
                    next.delete(id);
                    return next;
                  });
                }}
              />
            </Section>
            {canSetGroupPolicies && stagedGroups.length > 0 && (
              <Section gap={2} height="auto" alignItems="stretch">
                <Content
                  font="main-ui-action"
                  title={shareCopy("groupInstallation.title")}
                  description={t("groupInstallationDescription")}
                />
                <Card border="solid" padding={2}>
                  <Section gap={1} height="auto" alignItems="stretch">
                    {stagedGroups.map((group) => (
                      <ShareAccessRow
                        key={group.id}
                        avatarIcon={SvgUsers}
                        icon={SvgUsers}
                        title={group.name}
                        rightChildren={
                          <SharePermissionMenu
                            ariaLabel={shareCopy(
                              "groupInstallation.ariaLabel",
                              {
                                name: group.name,
                              }
                            )}
                            disabled={saving}
                            menuWidth={70}
                            value={groupPolicies.get(group.id) ?? "KEEP"}
                            options={groupPolicyOptions}
                            onChange={(choice) =>
                              setGroupPolicies((current) =>
                                new Map(current).set(group.id, choice)
                              )
                            }
                          />
                        }
                      />
                    ))}
                  </Section>
                </Card>
              </Section>
            )}
            {followingMarketplaceCount > 0 && (
              <MessageCard
                variant="warning"
                title={t("detachWarning", { count: followingMarketplaceCount })}
              />
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button
            prominence="secondary"
            disabled={saving}
            onClick={() => {
              reset();
              onClose();
            }}
          >
            {shareCopy("cancelButton.label")}
          </Button>
          <Button disabled={!changed || saving} onClick={() => void save()}>
            {t("apply", { count })}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
