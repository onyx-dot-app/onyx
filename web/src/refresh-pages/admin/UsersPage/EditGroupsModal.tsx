"use client";

import { useState, useMemo, useRef, useCallback } from "react";
import { Button } from "@opal/components";
import { SvgUsers, SvgUser, SvgLogOut } from "@opal/icons";
import { Disabled } from "@opal/core";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Separator from "@/refresh-components/Separator";
import { toast } from "@/hooks/useToast";
import { UserRole } from "@/lib/types";
import useGroups from "@/hooks/useGroups";
import { addUserToGroup, removeUserFromGroup, setUserRole } from "./svc";
import type { UserRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ASSIGNABLE_ROLES: { value: UserRole; label: string }[] = [
  { value: UserRole.ADMIN, label: "Admin" },
  { value: UserRole.BASIC, label: "Basic" },
];

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
  const [selectedRole, setSelectedRole] = useState<string>(user.role ?? "");

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

  const hasRoleChange = user.role !== null && selectedRole !== user.role;
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
      const promises: Promise<void>[] = [];

      const toAdd = Array.from(memberGroupIds).filter(
        (id) => !initialMemberGroupIds.has(id)
      );
      const toRemove = Array.from(initialMemberGroupIds).filter(
        (id) => !memberGroupIds.has(id)
      );

      if (user.id) {
        for (const groupId of toAdd) {
          promises.push(addUserToGroup(groupId, user.id));
        }
        for (const groupId of toRemove) {
          const group = allGroups?.find((g) => g.id === groupId);
          if (group) {
            const currentUserIds = group.users.map((u) => u.id);
            promises.push(
              removeUserFromGroup(groupId, currentUserIds, user.id)
            );
          }
        }
      }

      if (hasRoleChange) {
        promises.push(setUserRole(user.email, selectedRole));
      }

      await Promise.all(promises);
      onMutate();
      toast.success("User updated");
      onClose();
    } catch (err) {
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
          description={`${displayName} (${user.email})`}
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <div className="flex flex-col gap-3 w-full min-h-[240px]">
            <div ref={containerRef} className="relative w-full">
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
                <div className="absolute top-full left-0 right-0 z-50 mt-1 bg-background-neutral-00 border border-border-02 rounded-12 shadow-md max-h-[200px] overflow-y-auto p-1">
                  {groupsLoading ? (
                    <div className="px-3 py-2">
                      <Text as="p" text03 secondaryBody>
                        Loading groups...
                      </Text>
                    </div>
                  ) : dropdownGroups.length === 0 ? (
                    <div className="px-3 py-2">
                      <Text as="p" text03 secondaryBody>
                        No groups found
                      </Text>
                    </div>
                  ) : (
                    dropdownGroups.map((group, idx) => {
                      const isMember = memberGroupIds.has(group.id);
                      return (
                        <button
                          key={group.id}
                          type="button"
                          onMouseDown={(e) => e.preventDefault()}
                          onClick={() => toggleGroup(group.id)}
                          className={`flex items-center justify-between gap-2 px-3 py-2.5 w-full hover:bg-background-neutral-02 transition-colors text-left rounded-lg ${
                            idx > 0 ? "border-t border-border-01" : ""
                          }`}
                        >
                          <div className="flex flex-col gap-0.5">
                            <Text as="span" mainUiAction text05>
                              {group.name}
                            </Text>
                            <Text as="span" secondaryBody text03>
                              {group.users.length}{" "}
                              {group.users.length === 1 ? "user" : "users"}
                            </Text>
                          </div>
                          {isMember && (
                            <Text as="span" secondaryBody text03>
                              Joined
                            </Text>
                          )}
                        </button>
                      );
                    })
                  )}
                </div>
              )}
            </div>

            {joinedGroups.length === 0 ? (
              <div className="flex items-start gap-3 px-3 py-2">
                <SvgUsers className="w-4 h-4 text-text-03 flex-shrink-0 mt-0.5" />
                <div className="flex flex-col gap-0.5">
                  <Text as="span" mainUiAction text05>
                    No groups found
                  </Text>
                  <Text as="span" secondaryBody text03>
                    {displayName} is not in any groups.
                  </Text>
                </div>
              </div>
            ) : (
              <div className="flex flex-col overflow-y-auto max-h-[200px]">
                {joinedGroups.map((group, idx) => (
                  <button
                    key={group.id}
                    type="button"
                    onClick={() => toggleGroup(group.id)}
                    className={`flex items-center justify-between gap-2 px-3 py-2.5 hover:bg-background-neutral-02 transition-colors text-left ${
                      idx > 0 ? "border-t border-border-01" : ""
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <SvgUsers className="w-4 h-4 text-text-03 flex-shrink-0" />
                      <div className="flex flex-col gap-0.5">
                        <Text as="span" mainUiAction text05>
                          {group.name}
                        </Text>
                        <Text as="span" secondaryBody text03>
                          {group.users.length}{" "}
                          {group.users.length === 1 ? "user" : "users"}
                        </Text>
                      </div>
                    </div>
                    <SvgLogOut className="w-4 h-4 text-text-03 flex-shrink-0" />
                  </button>
                ))}
              </div>
            )}
          </div>
        </Modal.Body>

        {user.role && (
          <>
            <Separator noPadding />

            <div className="flex items-center justify-between w-full gap-4 px-4 py-3">
              <div className="flex flex-col gap-0.5">
                <Text as="p" mainUiAction text04>
                  User Role
                </Text>
                <Text as="p" secondaryBody text03>
                  This controls their general permissions.
                </Text>
              </div>

              <div className="w-[200px] flex-shrink-0">
                <InputSelect
                  value={selectedRole}
                  onValueChange={setSelectedRole}
                >
                  <InputSelect.Trigger />
                  <InputSelect.Content>
                    {ASSIGNABLE_ROLES.map(({ value, label }) => (
                      <InputSelect.Item
                        key={value}
                        value={value}
                        icon={SvgUser}
                      >
                        {label}
                      </InputSelect.Item>
                    ))}
                  </InputSelect.Content>
                </InputSelect>
              </div>
            </div>
          </>
        )}

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
