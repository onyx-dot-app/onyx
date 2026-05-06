"use client";

import { useState, useMemo, useCallback } from "react";
import { Button, Divider } from "@opal/components";
import { SvgUsers, SvgUser, SvgLogOut, SvgCheck } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Popover from "@/refresh-components/Popover";
import LineItem from "@/refresh-components/buttons/LineItem";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import { Tooltip } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import useGroups from "@/hooks/useGroups";
import { addUserToGroup, removeUserFromGroup, setUserRole } from "./svc";
import type { UserRow } from "./interfaces";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ASSIGNABLE_ROLES: UserRole[] = [
  UserRole.ADMIN,
  UserRole.GLOBAL_CURATOR,
  UserRole.BASIC,
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EditUserModalProps {
  user: UserRow & { id: string };
  onClose: () => void;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EditUserModal({
  user,
  onClose,
  onMutate,
}: EditUserModalProps) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();
  const { data: allGroups, isLoading: groupsLoading } = useGroups();
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [selectedRole, setSelectedRole] = useState<UserRole | "">(
    user.role ?? ""
  );

  const initialMemberGroupIds = useMemo(
    () => new Set(user.groups.map((g) => g.id)),
    [user.groups]
  );
  const [memberGroupIds, setMemberGroupIds] = useState<Set<number>>(
    () => new Set(initialMemberGroupIds)
  );

  // Dropdown shows all groups filtered by search term
  const dropdownGroups = useMemo(() => {
    if (!allGroups) return [];
    if (searchTerm.length === 0) return allGroups;
    const lower = searchTerm.toLowerCase();
    return allGroups.filter((g) => g.name.toLowerCase().includes(lower));
  }, [allGroups, searchTerm]);

  // Joined groups shown in the modal body
  const joinedGroups = useMemo(() => {
    if (!allGroups) return [];
    return allGroups.filter((g) => memberGroupIds.has(g.id));
  }, [allGroups, memberGroupIds]);

  const hasGroupChanges = useMemo(() => {
    if (memberGroupIds.size !== initialMemberGroupIds.size) return true;
    return Array.from(memberGroupIds).some(
      (id) => !initialMemberGroupIds.has(id)
    );
  }, [memberGroupIds, initialMemberGroupIds]);

  const visibleRoles = isPaidEnterpriseFeaturesEnabled
    ? ASSIGNABLE_ROLES
    : ASSIGNABLE_ROLES.filter((r) => r !== UserRole.GLOBAL_CURATOR);

  const hasRoleChange =
    user.role !== null && selectedRole !== "" && selectedRole !== user.role;
  const hasChanges = hasGroupChanges || hasRoleChange;

  const toggleGroup = (groupId: number) => {
    setMemberGroupIds((prev) => {
      const next = new Set(prev);
      if (next.has(groupId)) {
        next.delete(groupId);
      } else {
        next.add(groupId);
      }
      return next;
    });
  };

  const handleSave = async () => {
    setIsSubmitting(true);
    try {
      const toAdd = Array.from(memberGroupIds).filter(
        (id) => !initialMemberGroupIds.has(id)
      );
      const toRemove = Array.from(initialMemberGroupIds).filter(
        (id) => !memberGroupIds.has(id)
      );

      if (user.id) {
        for (const groupId of toAdd) {
          await addUserToGroup(groupId, user.id);
        }
        for (const groupId of toRemove) {
          const group = allGroups?.find((g) => g.id === groupId);
          if (group) {
            const currentUserIds = group.users.map((u) => u.id);
            const ccPairIds = group.cc_pairs.map((cc) => cc.id);
            await removeUserFromGroup(
              groupId,
              currentUserIds,
              user.id,
              ccPairIds
            );
          }
        }
      }

      if (
        user.role !== null &&
        selectedRole !== "" &&
        selectedRole !== user.role
      ) {
        await setUserRole(user.email, selectedRole);
      }

      onMutate();
      toast.success("User updated");
      onClose();
    } catch (err) {
      onMutate(); // refresh to show partially-applied state
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  };

  const displayName = user.personal_name ?? user.email;
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
          title="Edit User's Groups & Roles"
          description={
            user.personal_name
              ? `${user.personal_name} (${user.email})`
              : user.email
          }
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
                      leftSearchIcon
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
                      className={cn(
                        "flex flex-col gap-1 max-h-[15rem] rounded-08"
                      )}
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
                className={cn(" max-h-[11rem] flex flex-col gap-1 rounded-08")}
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
            {user.role && (
              <>
                <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                <ContentAction
                  title="User Role"
                  description="This controls their general permissions."
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
                        {user.role && !visibleRoles.includes(user.role) && (
                          <InputSelect.Item
                            key={user.role}
                            value={user.role}
                            icon={SvgUser}
                          >
                            {USER_ROLE_LABELS[user.role]}
                          </InputSelect.Item>
                        )}
                        {visibleRoles.map((role) => (
                          <InputSelect.Item
                            key={role}
                            value={role}
                            icon={SvgUser}
                          >
                            {USER_ROLE_LABELS[role]}
                          </InputSelect.Item>
                        ))}
                      </InputSelect.Content>
                    </InputSelect>
                  }
                />
              </>
            )}
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
