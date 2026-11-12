"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  InputSingleSelect,
  MessageCard,
  Modal,
  Text,
} from "@opal/components";
import { Content, Section } from "@opal/layouts";
import { SvgBlocks, SvgOrganization, SvgUsers } from "@opal/icons";
import { useUser } from "@/providers/UserProvider";
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
import type { GroupAccessRow } from "@/lib/skills/sharing";
import {
  fromPolicyChoice,
  isPolicyChoice,
  usePolicyOptions,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { SharePermissionMenu } from "@/lib/permissions/components";
import SkillGroupAccess from "@/sections/modals/skills/SkillGroupAccess";

const KEEP = "KEEP";

interface BulkSkillSharingModalProps {
  count: number;
  // False when a selected skill's organization access is not the caller's to
  // change (owner or admin only); the API would reject that skill's update.
  canChangeOrgAccess: boolean;
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onSave: (sharing: SkillShareUpdatePayload) => Promise<void>;
}

export default function BulkSkillSharingModal({
  count,
  canChangeOrgAccess,
  open,
  saving,
  onClose,
  onSave,
}: BulkSkillSharingModalProps) {
  const t = useTranslations("skills.bulk");
  const shareCopy = useTranslations("skills.modals.share");
  const { isAdmin } = useUser();
  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
  const canSetGroupSettings = isGlobalHolder || isScopedManager;
  const companyOptions = usePolicyOptions({
    inherit: { scope: "skill", policy: null },
  });
  const { data: users } = useShareableUsers({ includeApiKeys: true });
  const { data: groups } = useShareableGroups();
  // Publishing is one-way, so bulk can publish but never make skills private.
  const [scope, setScope] = useState<"KEEP" | "PUBLIC">("KEEP");
  const [policy, setPolicy] = useState<typeof KEEP | PolicyChoice>(KEEP);
  const [groupRows, setGroupRows] = useState<GroupAccessRow[]>([]);
  const [permission, setPermission] = useState<SkillSharePermission>("VIEWER");
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const changed =
    scope !== "KEEP" ||
    policy !== KEEP ||
    groupRows.length > 0 ||
    stagedUsers.length > 0 ||
    stagedGroups.length > 0;

  // The parent keeps this modal mounted, so a generic close (X, backdrop)
  // keeps the staged edits. Cancel and a submitted save discard them.
  function reset() {
    setScope("KEEP");
    setPolicy(KEEP);
    setGroupRows([]);
    setPermission("VIEWER");
    setStagedUsers([]);
    setStagedGroups([]);
  }

  async function save() {
    const sharing: SkillShareUpdatePayload = {};
    if (scope === "PUBLIC") sharing.public_permission = "VIEWER";
    if (policy !== KEEP) sharing.installation_policy = fromPolicyChoice(policy);
    // A listed group gets its setting on every skill; the organization setting
    // clears it.
    if (groupRows.length)
      sharing.group_settings = groupRows.map((row) => ({
        group_id: row.group_id,
        installation_policy: fromPolicyChoice(row.choice),
      }));
    if (stagedUsers.length)
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
                value={scope}
                onChange={setScope}
                ariaLabel={shareCopy("accessTitle")}
                disabled={saving || !canChangeOrgAccess}
                options={[
                  { value: "KEEP", label: t("unchanged"), icon: SvgUsers },
                  {
                    value: "PUBLIC",
                    label: t("everyone"),
                    icon: SvgOrganization,
                  },
                ]}
              />
              {scope === "PUBLIC" && (
                <MessageCard
                  variant="warning"
                  outerPadding={1}
                  innerPadding={1}
                  title={t("publishWarning.title")}
                  description={t("publishWarning.description")}
                />
              )}
            </Section>
            {isAdmin && (
              <Section gap={2} height="auto" alignItems="stretch">
                <Content
                  font="main-ui-action"
                  title={shareCopy("installation.title")}
                />
                <InputSingleSelect
                  placeholder={shareCopy("installation.title")}
                  value={policy}
                  defaultOption={KEEP}
                  disabled={saving}
                  options={[
                    { value: KEEP, title: t("unchanged") },
                    ...companyOptions,
                  ]}
                  onValueChange={(value) => {
                    if (value === KEEP || isPolicyChoice(value))
                      setPolicy(value);
                  }}
                />
              </Section>
            )}
            {canSetGroupSettings && (
              <SkillGroupAccess
                rows={groupRows}
                company={null}
                groups={groups ?? []}
                description={shareCopy("groupAccess.bulkDescription")}
                disabled={saving}
                onChange={setGroupRows}
              />
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
                users={users ?? []}
                groups={groups ?? []}
                stagedUsers={stagedUsers}
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
