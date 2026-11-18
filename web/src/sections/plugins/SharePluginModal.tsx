"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { BasicModalFooter, Button, MessageCard, Modal } from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { SvgShare, SvgUser, SvgUsers, SvgX } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import useShareableUsers from "@/hooks/useShareableUsers";
import { updatePluginAccess } from "@/lib/integrations/svc";
import type {
  PluginAccessView,
  PluginSharePermission,
} from "@/lib/integrations/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { MinimalUserSnapshot } from "@/lib/types";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import {
  applyStagedShares,
  type ShareDraftState,
} from "@/sections/modals/shareDraftState";

type PluginShareDraft = ShareDraftState<PluginSharePermission>;

function draftFrom(view: PluginAccessView): PluginShareDraft {
  return {
    userShares: view.user_shares.map((share) => ({
      user: { id: share.user_id, email: share.email },
      permission: share.permission,
    })),
    groupShares: view.group_shares,
    isPublic: false,
    publicPermission: "VIEWER",
  };
}

export interface SharePluginModalProps {
  pluginId: string;
  pluginName: string;
  /** Names of its integrations with shared sign-in: people with a share use
   * the account that the owner connected. */
  sharedSignIn: string[];
  onClose: () => void;
  onSaved: () => void;
}

export default function SharePluginModal({
  pluginId,
  pluginName,
  sharedSignIn,
  onClose,
  onSaved,
}: SharePluginModalProps) {
  const t = useTranslations("plugins.member.share");
  const { data, error, mutate } = useSWR<PluginAccessView, Error>(
    SWR_KEYS.pluginAccess(pluginId),
    errorHandlingFetcher
  );
  const { data: users } = useShareableUsers({ includeApiKeys: false });
  const { data: groups } = useShareableGroups();
  const [edited, setEdited] = useState<PluginShareDraft | null>(null);
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [stagedPermission, setStagedPermission] =
    useState<PluginSharePermission>("VIEWER");
  const [busy, setBusy] = useState(false);

  const draft = edited ?? (data ? draftFrom(data) : null);
  const currentUsers = draft?.userShares ?? [];
  const currentGroups = draft?.groupShares ?? [];

  function edit(change: (current: PluginShareDraft) => PluginShareDraft) {
    if (draft) setEdited(change(draft));
  }

  async function save() {
    if (!draft) return;
    const next = applyStagedShares(
      draft,
      stagedUsers,
      stagedGroups,
      stagedPermission
    );
    setBusy(true);
    try {
      const saved = await updatePluginAccess(pluginId, {
        user_shares: next.userShares.map((share) => ({
          user_id: share.user.id,
          permission: share.permission,
        })),
        group_shares: next.groupShares.map((share) => ({
          group_id: share.group_id,
          permission: share.permission,
        })),
      });
      // A reopened dialog starts from the cache, so it must hold the saved list.
      await mutate(saved, { revalidate: false });
      toast.success(t("saved", { name: pluginName }));
      onSaved();
    } catch (saveError) {
      toast.error(saveError instanceof Error ? saveError.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onOpenChange={(open) => !open && !busy && onClose()}>
      <Modal.Content width="md" preventAccidentalClose={false}>
        <Modal.Header
          icon={SvgShare}
          title={t("title", { name: pluginName })}
          description={t("description")}
          onClose={busy ? undefined : onClose}
        />
        <Modal.Body padding={4} gap={4} alignItems="stretch">
          {sharedSignIn.length > 0 && (
            <MessageCard
              variant="info"
              title={t("sharedSignIn", { names: sharedSignIn.join(", ") })}
            />
          )}
          {error && <MessageCard variant="error" title={t("loadFailed")} />}
          <AddPeoplePicker
            disabled={busy || draft === null}
            existingUserIds={
              new Set(currentUsers.map((share) => share.user.id))
            }
            existingGroupIds={
              new Set(currentGroups.map((share) => share.group_id))
            }
            users={users ?? []}
            groups={groups ?? []}
            stagedUsers={stagedUsers}
            stagedGroups={stagedGroups}
            stagedPermission={stagedPermission}
            onStagedPermissionChange={setStagedPermission}
            onAddUser={(user) => setStagedUsers((staged) => [...staged, user])}
            onAddGroup={(group) =>
              setStagedGroups((staged) => [...staged, group])
            }
            onRemoveUser={(userId) =>
              setStagedUsers((staged) =>
                staged.filter((user) => user.id !== userId)
              )
            }
            onRemoveGroup={(groupId) =>
              setStagedGroups((staged) =>
                staged.filter((group) => group.id !== groupId)
              )
            }
          />
          <Section gap={1} alignItems="stretch" height="auto">
            {currentUsers.length === 0 && currentGroups.length === 0 && (
              <MessageCard variant="default" title={t("empty")} />
            )}
            {currentUsers.map((share) => (
              <ShareAccessRow
                key={share.user.id}
                icon={SvgUser}
                avatarInitial={share.user.email.charAt(0).toUpperCase()}
                title={share.user.email}
                rightChildren={
                  <Button
                    size="sm"
                    prominence="tertiary"
                    icon={SvgX}
                    disabled={busy}
                    aria-label={t("remove.label", { name: share.user.email })}
                    onClick={() =>
                      edit((current) => ({
                        ...current,
                        userShares: current.userShares.filter(
                          (other) => other.user.id !== share.user.id
                        ),
                      }))
                    }
                  />
                }
              />
            ))}
            {currentGroups.map((share) => (
              <ShareAccessRow
                key={share.group_id}
                icon={SvgUsers}
                avatarIcon={SvgUsers}
                title={share.group_name}
                rightChildren={
                  <Button
                    size="sm"
                    prominence="tertiary"
                    icon={SvgX}
                    disabled={busy}
                    aria-label={t("remove.label", { name: share.group_name })}
                    onClick={() =>
                      edit((current) => ({
                        ...current,
                        groupShares: current.groupShares.filter(
                          (other) => other.group_id !== share.group_id
                        ),
                      }))
                    }
                  />
                }
              />
            ))}
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" disabled={busy} onClick={onClose}>
                {t("cancel.label")}
              </Button>
            }
            submit={
              <Button
                disabled={busy || draft === null}
                onClick={() => void save()}
              >
                {busy ? t("submit.pendingLabel") : t("submit.label")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
