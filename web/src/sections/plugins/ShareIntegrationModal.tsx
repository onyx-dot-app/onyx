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
import { updateIntegrationShares } from "@/lib/integrations/svc";
import type {
  IntegrationSharesView,
  MemberIntegration,
} from "@/lib/integrations/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { MinimalUserSnapshot } from "@/lib/types";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";

type UserShare = IntegrationSharesView["user_shares"][number];
type GroupShare = IntegrationSharesView["group_shares"][number];

interface ShareDraft {
  users: UserShare[];
  groups: GroupShare[];
}

export interface ShareIntegrationModalProps {
  integration: Pick<MemberIntegration, "id" | "name" | "auth_mode">;
  onClose: () => void;
  onSaved: () => void;
}

/** Share a private integration with specific people, and with groups in
 * the Enterprise edition. A share gives use of the integration only. */
export default function ShareIntegrationModal({
  integration,
  onClose,
  onSaved,
}: ShareIntegrationModalProps) {
  const t = useTranslations("integrations.share");
  const { data, error, mutate } = useSWR<IntegrationSharesView, Error>(
    SWR_KEYS.integrationAccess(integration.id),
    errorHandlingFetcher
  );
  const { data: users } = useShareableUsers({ includeApiKeys: false });
  const { data: groups } = useShareableGroups();
  const [edited, setEdited] = useState<ShareDraft | null>(null);
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [busy, setBusy] = useState(false);

  const draft: ShareDraft | null =
    edited ??
    (data ? { users: data.user_shares, groups: data.group_shares } : null);
  const currentUsers = draft?.users ?? [];
  const currentGroups = draft?.groups ?? [];

  function edit(change: (current: ShareDraft) => ShareDraft) {
    if (draft) setEdited(change(draft));
  }

  async function save() {
    if (!draft) return;
    const userIds = new Set([
      ...draft.users.map((share) => share.user_id),
      ...stagedUsers.map((user) => user.id),
    ]);
    const groupIds = new Set([
      ...draft.groups.map((share) => share.group_id),
      ...stagedGroups.map((group) => group.id),
    ]);
    setBusy(true);
    try {
      const saved = await updateIntegrationShares(integration.id, {
        user_ids: [...userIds],
        group_ids: [...groupIds],
      });
      // A reopened dialog starts from the cache, so it must hold the saved list.
      await mutate(saved, { revalidate: false });
      toast.success(t("saved", { name: integration.name }));
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
          title={t("title", { name: integration.name })}
          description={t("description")}
          onClose={busy ? undefined : onClose}
        />
        <Modal.Body padding={4} gap={4} alignItems="stretch">
          {integration.auth_mode === "shared" && (
            <MessageCard
              variant="info"
              title={t("sharedSignIn", { name: integration.name })}
            />
          )}
          {error && <MessageCard variant="error" title={t("loadFailed")} />}
          <AddPeoplePicker
            disabled={busy || draft === null}
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
                      edit((current) => ({
                        ...current,
                        users: current.users.filter(
                          (other) => other.user_id !== share.user_id
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
                        groups: current.groups.filter(
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
