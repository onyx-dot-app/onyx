"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Modal, Text } from "@opal/components";
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
import { SharePermissionMenu } from "@/lib/permissions/components";
import { useSharePermissionOptions } from "@/sections/modals/shareAccessConstants";
import { useInstallationPolicyOptions } from "@/lib/skills/hooks";

interface BulkSkillSharingModalProps {
  count: number;
  canChangeOrgAccess: boolean;
  canChangeUserAccess: boolean;
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onSave: (sharing: SkillShareUpdatePayload) => Promise<void>;
}

export default function BulkSkillSharingModal({
  count,
  canChangeOrgAccess,
  canChangeUserAccess,
  open,
  saving,
  onClose,
  onSave,
}: BulkSkillSharingModalProps) {
  const t = useTranslations("skills.bulk");
  const shareCopy = useTranslations("skills.modals.share");
  const { isGlobalHolder: canManageCompanySkills } = usePermissionAuthority(
    Permission.MANAGE_SKILLS
  );
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
  const permissionOptions = useSharePermissionOptions();
  const installationOptions = useInstallationPolicyOptions();
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
      sharing.group_shares = stagedGroups.map((group) => ({
        group_id: group.id,
        permission,
      }));
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
                onRemoveGroup={(id) =>
                  setStagedGroups((current) =>
                    current.filter((group) => group.id !== id)
                  )
                }
              />
            </Section>
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
