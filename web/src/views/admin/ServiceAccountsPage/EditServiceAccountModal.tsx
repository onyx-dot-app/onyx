"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { Button, Divider } from "@opal/components";
import { SvgUsers, SvgLogOut, SvgCheck } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";
import { InputTypeIn } from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import { Popover } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import { ShadowDiv } from "@opal/components";
import { Tooltip } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import useGroups from "@/hooks/useGroups";
import {
  addUserToGroup,
  removeUserFromGroup,
} from "@/views/admin/UsersPage/svc";
import { updateApiKey } from "@/views/admin/ServiceAccountsPage/svc";
import { SERVICE_ACCOUNT_ROLE_OPTIONS } from "@/views/admin/ServiceAccountsPage/interfaces";
import type { APIKey } from "@/views/admin/ServiceAccountsPage/interfaces";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

const setsAreEqual = (a: Set<number>, b: Set<number>): boolean =>
  a.size === b.size && Array.from(a).every((value) => b.has(value));

interface EditServiceAccountModalProps {
  apiKey: APIKey;
  onClose: () => void;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EditServiceAccountModal({
  apiKey,
  onClose,
  onMutate,
}: EditServiceAccountModalProps) {
  const {
    data: allGroups,
    isLoading: groupsLoading,
    refreshGroups,
  } = useGroups();
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [selectedRole, setSelectedRole] = useState<UserRole>(
    apiKey.api_key_role
  );

  // The API-key's synthetic user is a real group member, so derive current
  // membership from the groups list (defaults are excluded server-side).
  const initialMemberGroupIds = useMemo(
    () =>
      new Set(
        (allGroups ?? [])
          .filter((g) => g.users.some((u) => u.id === apiKey.user_id))
          .map((g) => g.id)
      ),
    [allGroups, apiKey.user_id]
  );

  // null until the admin edits — lets the derived set populate after groups
  // load without an effect, while a non-null value holds explicit edits.
  const [editedGroupIds, setEditedGroupIds] = useState<Set<number> | null>(
    null
  );
  // Tracks the live membership until the admin starts editing, then freezes.
  // Save diffs against this baseline so it applies only this admin's deltas —
  // a concurrent edit by another admin to the same account isn't clobbered.
  const [baselineGroupIds, setBaselineGroupIds] = useState(
    initialMemberGroupIds
  );

  useEffect(() => {
    if (editedGroupIds === null) {
      setBaselineGroupIds((prev) =>
        setsAreEqual(prev, initialMemberGroupIds) ? prev : initialMemberGroupIds
      );
    }
  }, [initialMemberGroupIds, editedGroupIds]);

  const memberGroupIds = editedGroupIds ?? initialMemberGroupIds;

  const dropdownGroups = useMemo(() => {
    if (!allGroups) return [];
    if (searchTerm.length === 0) return allGroups;
    const lower = searchTerm.toLowerCase();
    return allGroups.filter((g) => g.name.toLowerCase().includes(lower));
  }, [allGroups, searchTerm]);

  const joinedGroups = useMemo(() => {
    if (!allGroups) return [];
    return allGroups.filter((g) => memberGroupIds.has(g.id));
  }, [allGroups, memberGroupIds]);

  const hasGroupChanges = useMemo(() => {
    if (memberGroupIds.size !== baselineGroupIds.size) return true;
    return Array.from(memberGroupIds).some((id) => !baselineGroupIds.has(id));
  }, [memberGroupIds, baselineGroupIds]);

  const hasRoleChange = selectedRole !== apiKey.api_key_role;
  const hasChanges = hasGroupChanges || hasRoleChange;

  const toggleGroup = (groupId: number) => {
    setEditedGroupIds((prev) => {
      const next = new Set(prev ?? baselineGroupIds);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return setsAreEqual(next, baselineGroupIds) ? null : next;
    });
  };

  const handleSave = async () => {
    setIsSubmitting(true);
    try {
      const toAdd = Array.from(memberGroupIds).filter(
        (id) => !baselineGroupIds.has(id)
      );
      const toRemove = Array.from(baselineGroupIds).filter(
        (id) => !memberGroupIds.has(id)
      );

      for (const groupId of toAdd) {
        await addUserToGroup(groupId, apiKey.user_id);
      }
      // Removal replaces the group's member list with the cached snapshot
      // minus this account; concurrent edits to the same group lose.
      for (const groupId of toRemove) {
        const group = allGroups?.find((g) => g.id === groupId);
        if (group) {
          const currentUserIds = group.users.map((u) => u.id);
          const ccPairIds = group.cc_pairs.map((cc) => cc.id);
          await removeUserFromGroup(
            groupId,
            currentUserIds,
            apiKey.user_id,
            ccPairIds
          );
        }
      }

      if (selectedRole !== apiKey.api_key_role) {
        const res = await updateApiKey(apiKey.api_key_id, {
          name: apiKey.api_key_name ?? undefined,
          role: selectedRole,
        });
        if (!res.ok) {
          throw new Error((await res.text()) || "Failed to update role");
        }
      }

      onMutate();
      refreshGroups();
      toast.success("Service account updated");
      onClose();
    } catch (err) {
      // Partial writes may have landed — refresh both caches.
      onMutate();
      refreshGroups();
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  };

  const displayName = apiKey.api_key_name || "Unnamed";
  const [contentEl, setContentEl] = useState<HTMLDivElement | null>(null);
  const contentRef = useCallback((node: HTMLDivElement | null) => {
    setContentEl(node);
  }, []);

  return (
    <Modal
      open
      onOpenChange={(isOpen) => !isOpen && !isSubmitting && onClose()}
    >
      <Modal.Content width="sm" ref={contentRef}>
        <Modal.Header
          icon={SvgUsers}
          title={`Edit ${displayName}'s Groups & Roles`}
          description={apiKey.api_key_display}
          onClose={isSubmitting ? undefined : onClose}
        />
        <Modal.Body twoTone>
          <Section padding={0} height="auto" alignItems="stretch">
            <Section
              gap={0.5}
              padding={0.25}
              height={joinedGroups.length === 0 && !popoverOpen ? "auto" : 14.5}
              alignItems="stretch"
              justifyContent="start"
              className="bg-background-tint-02 rounded-08"
            >
              <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
                <Popover.Trigger asChild>
                  {/* asChild merges trigger props onto this div instead of rendering a <button>.
                     Without it, the trigger <button> would nest around InputTypeIn's
                     internal IconButton <button>, causing a hydration error. */}
                  <div>
                    <InputTypeIn
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      placeholder="Search groups to join..."
                      searchIcon
                    />
                  </div>
                </Popover.Trigger>
                <Popover.Content
                  width="trigger"
                  align="start"
                  container={contentEl}
                >
                  {groupsLoading ? (
                    <LineItem skeleton description="Loading groups...">
                      Loading...
                    </LineItem>
                  ) : dropdownGroups.length === 0 ? (
                    <LineItem
                      skeleton
                      description="Try a different search term."
                    >
                      No groups found
                    </LineItem>
                  ) : (
                    <ShadowDiv
                      shadowHeight="0.75rem"
                      className={cn("flex flex-col gap-1 max-h-60 rounded-08")}
                    >
                      {dropdownGroups.map((group) => {
                        const isMember = memberGroupIds.has(group.id);
                        return (
                          <LineItem
                            key={group.id}
                            icon={isMember ? SvgCheck : SvgUsers}
                            description={`${group.users.length} ${
                              group.users.length === 1 ? "user" : "users"
                            }`}
                            selected={isMember}
                            emphasized={isMember}
                            onClick={() => toggleGroup(group.id)}
                          >
                            {group.name}
                          </LineItem>
                        );
                      })}
                    </ShadowDiv>
                  )}
                </Popover.Content>
              </Popover>

              <ShadowDiv
                className={cn(" max-h-44 flex flex-col gap-1 rounded-08")}
                shadowHeight="0.75rem"
              >
                {joinedGroups.length === 0 ? (
                  <LineItem
                    icon={SvgUsers}
                    skeleton
                    interactive={false}
                    description={`${displayName} is not in any groups.`}
                  >
                    No groups found
                  </LineItem>
                ) : (
                  joinedGroups.map((group) => (
                    <div
                      key={group.id}
                      className="bg-background-tint-01 rounded-08"
                    >
                      <LineItem
                        key={group.id}
                        icon={SvgUsers}
                        description={`${group.users.length} ${
                          group.users.length === 1 ? "user" : "users"
                        }`}
                        rightChildren={
                          <Tooltip tooltip="Remove from group" side="left">
                            <SvgLogOut height={16} width={16} />
                          </Tooltip>
                        }
                        onClick={() => toggleGroup(group.id)}
                      >
                        {group.name}
                      </LineItem>
                    </div>
                  ))
                )}
              </ShadowDiv>
            </Section>

            <Divider paddingParallel="fit" paddingPerpendicular="fit" />

            <ContentAction
              title="Account Role"
              description="This controls the service account's general permissions."
              sizePreset="main-ui"
              variant="section"
              padding="fit"
              rightChildren={
                <InputSelect
                  value={selectedRole}
                  onValueChange={(v) => setSelectedRole(v as UserRole)}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    {SERVICE_ACCOUNT_ROLE_OPTIONS.map((opt) => (
                      <InputSelect.Item
                        key={opt.role}
                        value={opt.role.toString()}
                        icon={opt.icon}
                        description={opt.description}
                      >
                        {USER_ROLE_LABELS[opt.role]}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>
              }
            />
          </Section>
        </Modal.Body>

        <Modal.Footer>
          <Button
            prominence="secondary"
            onClick={isSubmitting ? undefined : onClose}
          >
            Cancel
          </Button>
          <Button disabled={isSubmitting || !hasChanges} onClick={handleSave}>
            Save Changes
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
