"use client";

import { useState, useMemo, useRef, useCallback } from "react";
import { Button } from "@opal/components";
import { SvgUsers, SvgUser, SvgLogOut, SvgCheck } from "@opal/icons";
import { Disabled } from "@opal/core";
import { ContentAction } from "@opal/layouts";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import LineItem from "@/refresh-components/buttons/LineItem";
import Separator from "@/refresh-components/Separator";
import ShadowDiv from "@/refresh-components/ShadowDiv";
import { Section } from "@/layouts/general-layouts";
import { toast } from "@/hooks/useToast";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import useGroups from "@/hooks/useGroups";
import { addUserToGroup, removeUserFromGroup, setUserRole } from "./svc";
import type { UserRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ASSIGNABLE_ROLES: UserRole[] = [UserRole.ADMIN, UserRole.BASIC];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface EditGroupsModalProps {
  user: UserRow & { id: string };
  onClose: () => void;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function EditGroupsModal({
  user,
  onClose,
  onMutate,
}: EditGroupsModalProps) {
  const { data: allGroups, isLoading: groupsLoading } = useGroups();
  const [searchTerm, setSearchTerm] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const closeDropdown = useCallback(() => {
    // Delay to allow click events on dropdown items to fire before closing
    setTimeout(() => {
      if (!containerRef.current?.contains(document.activeElement)) {
        setDropdownOpen(false);
      }
    }, 0);
  }, []);
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

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgUsers}
          title="Edit User's Groups & Roles"
          description={
            user.personal_name
              ? `${user.personal_name} (${user.email})`
              : user.email
          }
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <Section
            gap={1}
            height="auto"
            alignItems="stretch"
            justifyContent="start"
          >
            {/* Subsection: white card behind search + groups */}
            <div className="relative">
              <div className="absolute -inset-2 bg-background-neutral-00 rounded-12" />
              <Section
                gap={0.5}
                height="auto"
                alignItems="stretch"
                justifyContent="start"
              >
                <div ref={containerRef} className="relative">
                  <InputTypeIn
                    value={searchTerm}
                    onChange={(e) => {
                      setSearchTerm(e.target.value);
                      if (!dropdownOpen) setDropdownOpen(true);
                    }}
                    onFocus={() => setDropdownOpen(true)}
                    onBlur={closeDropdown}
                    placeholder="Search groups to join..."
                    leftSearchIcon
                  />
                  {dropdownOpen && (
                    <div className="absolute top-full left-0 right-0 z-50 mt-1 bg-background-neutral-00 border border-border-02 rounded-12 shadow-md p-1">
                      {groupsLoading ? (
                        <Text as="p" text03 secondaryBody className="px-3 py-2">
                          Loading groups...
                        </Text>
                      ) : dropdownGroups.length === 0 ? (
                        <Text as="p" text03 secondaryBody className="px-3 py-2">
                          No groups found
                        </Text>
                      ) : (
                        <ShadowDiv className="max-h-[200px] flex flex-col gap-1">
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
                                onMouseDown={(e: React.MouseEvent) =>
                                  e.preventDefault()
                                }
                                onClick={() => toggleGroup(group.id)}
                              >
                                {group.name}
                              </LineItem>
                            );
                          })}
                        </ShadowDiv>
                      )}
                    </div>
                  )}
                </div>

                {joinedGroups.length === 0 ? (
                  <LineItem
                    icon={SvgUsers}
                    description={`${displayName} is not in any groups.`}
                    muted
                  >
                    No groups joined
                  </LineItem>
                ) : (
                  <ShadowDiv className="flex flex-col gap-1 max-h-[200px]">
                    {joinedGroups.map((group) => (
                      <div
                        key={group.id}
                        className="bg-background-tint-01 rounded-08"
                      >
                        <LineItem
                          icon={SvgUsers}
                          description={`${group.users.length} ${
                            group.users.length === 1 ? "user" : "users"
                          }`}
                          rightChildren={
                            <SvgLogOut className="w-4 h-4 text-text-03" />
                          }
                          onClick={() => toggleGroup(group.id)}
                        >
                          {group.name}
                        </LineItem>
                      </div>
                    ))}
                  </ShadowDiv>
                )}
              </Section>
            </div>

            {user.role && (
              <>
                <Separator noPadding />

                <ContentAction
                  title="User Role"
                  description="This controls their general permissions."
                  sizePreset="main-ui"
                  variant="section"
                  paddingVariant="fit"
                  rightChildren={
                    <InputSelect
                      value={selectedRole}
                      onValueChange={(v) => setSelectedRole(v as UserRole)}
                    >
                      <InputSelect.Trigger />
                      <InputSelect.Content>
                        {user.role && !ASSIGNABLE_ROLES.includes(user.role) && (
                          <InputSelect.Item
                            key={user.role}
                            value={user.role}
                            icon={SvgUser}
                          >
                            {USER_ROLE_LABELS[user.role]}
                          </InputSelect.Item>
                        )}
                        {ASSIGNABLE_ROLES.map((role) => (
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
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Disabled disabled={isSubmitting || !hasChanges}>
            <Button onClick={handleSave}>Save Changes</Button>
          </Disabled>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
