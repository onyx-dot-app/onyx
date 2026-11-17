"use client";

import { useEffect, useState } from "react";
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

interface UserShare {
  user_id: string;
  email: string;
  permission: PluginSharePermission;
}

interface GroupShare {
  group_id: number;
  group_name: string;
  permission: PluginSharePermission;
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
  const [userShares, setUserShares] = useState<UserShare[] | null>(null);
  const [groupShares, setGroupShares] = useState<GroupShare[] | null>(null);
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [stagedPermission, setStagedPermission] =
    useState<PluginSharePermission>("VIEWER");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!data || userShares !== null) return;
    setUserShares(data.user_shares);
    setGroupShares(data.group_shares);
  }, [data, userShares]);

  const currentUsers = userShares ?? [];
  const currentGroups = groupShares ?? [];

  async function save() {
    const nextUsers = new Map(
      currentUsers.map((share) => [share.user_id, share.permission])
    );
    for (const user of stagedUsers) nextUsers.set(user.id, stagedPermission);
    const nextGroups = new Map(
      currentGroups.map((share) => [share.group_id, share.permission])
    );
    for (const group of stagedGroups)
      nextGroups.set(group.id, stagedPermission);
    setBusy(true);
    try {
      const saved = await updatePluginAccess(pluginId, {
        user_shares: [...nextUsers].map(([user_id, permission]) => ({
          user_id,
          permission,
        })),
        group_shares: [...nextGroups].map(([group_id, permission]) => ({
          group_id,
          permission,
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
            disabled={busy || userShares === null}
            existingUserIds={
              new Set(currentUsers.map((share) => share.user_id))
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
                key={share.user_id}
                icon={SvgUser}
                avatarInitial={share.email.charAt(0).toUpperCase()}
                title={share.email}
                rightChildren={
                  <Button
                    size="sm"
                    prominence="tertiary"
                    icon={SvgX}
                    disabled={busy}
                    aria-label={t("remove.label", { name: share.email })}
                    onClick={() =>
                      setUserShares(
                        currentUsers.filter(
                          (other) => other.user_id !== share.user_id
                        )
                      )
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
                      setGroupShares(
                        currentGroups.filter(
                          (other) => other.group_id !== share.group_id
                        )
                      )
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
                disabled={busy || userShares === null}
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
