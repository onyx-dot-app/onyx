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
import { Content, InputPadder, Section } from "@opal/layouts";
import { SvgBlocks, SvgOrganization, SvgUsers } from "@opal/icons";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import useShareableUsers from "@/hooks/useShareableUsers";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import type { MinimalUserSnapshot } from "@/lib/types";
import type {
  CustomSkill,
  SkillInstallationPolicy,
  SkillSharePermission,
} from "@/lib/skills/types";
import type { SkillShareUpdatePayload } from "@/lib/skills/api";
import {
  fromPolicyChoice,
  isPolicyChoice,
  type PolicyChoice,
} from "@/lib/skills/installationPolicy";
import { usePolicyOptions, useSharingAllowed } from "@/lib/skills/hooks";
import SharingOffNotice from "@/sections/modals/skills/SharingOffNotice";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { SharePermissionMenu } from "@/lib/permissions/components";
import { canChangeOrganizationAccess } from "@/lib/skills/sharing";

const KEEP = "KEEP";

/** The strings that name the rows, as "skill" or "plugin". The skill strings
 * hold every key of the plugin strings. */
export type BulkNounCopy = ReturnType<typeof useTranslations<"plugins.bulk">>;

interface BulkSkillSharingModalProps {
  /** @default the skill strings */
  nounCopy?: BulkNounCopy;
  /** The selected skills. */
  items: readonly CustomSkill[];
  open: boolean;
  saving: boolean;
  onClose: () => void;
  onSave: (sharing: SkillShareUpdatePayload) => Promise<void>;
}

export default function BulkSkillSharingModal({
  nounCopy: givenNounCopy,
  items,
  open,
  saving,
  onClose,
  onSave,
}: BulkSkillSharingModalProps) {
  const bulkCopy = useTranslations("skills.bulk");
  const nounCopy = givenNounCopy ?? bulkCopy;
  const shareCopy = useTranslations("skills.modals.share");
  const { isGlobalHolder: isOrganizationManager } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
  const count = items.length;
  // The API rejects an organization access change the caller may not make.
  const canChangeOrgAccess = items.every((item) =>
    canChangeOrganizationAccess(item, isOrganizationManager)
  );
  const sharingAllowed = useSharingAllowed();
  const companyOptions = usePolicyOptions({
    inherit: { scope: "skill", policy: null },
  });
  const { data: users } = useShareableUsers({ includeApiKeys: true });
  const { data: groups } = useShareableGroups();
  // Publishing is one-way, so bulk can publish but never make skills private.
  const [stagedScope, setScope] = useState<"KEEP" | "PUBLIC">("KEEP");
  // A selection that loses organization access drops a staged publish.
  const scope = canChangeOrgAccess ? stagedScope : "KEEP";
  const [policy, setPolicy] = useState<typeof KEEP | PolicyChoice>(KEEP);
  const [permission, setPermission] = useState<SkillSharePermission>("VIEWER");
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const changed =
    scope !== "KEEP" ||
    policy !== KEEP ||
    stagedUsers.length > 0 ||
    stagedGroups.length > 0;

  // The parent keeps this modal mounted, so a generic close (X, backdrop)
  // keeps the staged edits. Cancel and a submitted save discard them.
  function reset() {
    setScope("KEEP");
    setPolicy(KEEP);
    setPermission("VIEWER");
    setStagedUsers([]);
    setStagedGroups([]);
  }

  async function save() {
    const sharing: SkillShareUpdatePayload = {};
    if (scope === "PUBLIC") sharing.public_permission = "VIEWER";
    if (policy !== KEEP) sharing.installation_policy = fromPolicyChoice(policy);
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
          title={nounCopy("shareTitle", { count })}
          description={nounCopy("shareDescription")}
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
                  {
                    value: "KEEP",
                    label: bulkCopy("unchanged"),
                    icon: SvgUsers,
                  },
                  {
                    value: "PUBLIC",
                    label: bulkCopy("everyone"),
                    icon: SvgOrganization,
                  },
                ]}
              />
              {scope === "PUBLIC" && (
                <MessageCard
                  variant="warning"
                  outerPadding={1}
                  innerPadding={1}
                  title={bulkCopy("publishWarning.title")}
                  description={nounCopy("publishWarning.description")}
                />
              )}
            </Section>
            {isOrganizationManager && (
              <Section gap={2} height="auto" alignItems="stretch">
                <Content
                  font="main-ui-action"
                  title={shareCopy("installation.title")}
                />
                <InputPadder>
                  <InputSingleSelect
                    placeholder={shareCopy("installation.title")}
                    value={policy}
                    defaultOption={KEEP}
                    disabled={saving}
                    options={[
                      { value: KEEP, title: bulkCopy("unchanged") },
                      ...companyOptions,
                    ]}
                    onValueChange={(value) => {
                      if (value === KEEP || isPolicyChoice(value))
                        setPolicy(value);
                    }}
                  />
                </InputPadder>
              </Section>
            )}
            <Section gap={2} height="auto" alignItems="stretch">
              <Content font="main-ui-action" title={shareCopy("peopleTitle")} />
              <Text font="secondary-body" color="text-03">
                {nounCopy("addAccessDescription")}
              </Text>
              {!sharingAllowed && <SharingOffNotice />}
              <AddPeoplePicker
                disabled={saving || !sharingAllowed}
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
            {nounCopy("apply", { count })}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
