"use client";

import { useState, useMemo } from "react";
import { Button, Tag } from "@opal/components";
import { SvgUsers } from "@opal/icons";
import { Disabled } from "@opal/core";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { toast } from "@/hooks/useToast";
import useGroups from "@/hooks/useGroups";
import { addUserToGroup, removeUserFromGroup } from "./svc";
import type { UserRow } from "./interfaces";

interface EditGroupsModalProps {
  user: UserRow & { id: string };
  onClose: () => void;
  onMutate: () => void;
}

export default function EditGroupsModal({
  user,
  onClose,
  onMutate,
}: EditGroupsModalProps) {
  const { data: allGroups, isLoading: groupsLoading } = useGroups();
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  // Track which groups the user is currently a member of (local state for optimistic toggling)
  const initialMemberGroupIds = useMemo(
    () => new Set(user.groups.map((g) => g.id)),
    [user.groups]
  );
  const [memberGroupIds, setMemberGroupIds] = useState<Set<number>>(
    () => new Set(initialMemberGroupIds)
  );

  const filteredGroups = useMemo(() => {
    if (!allGroups) return [];
    if (!searchTerm) return allGroups;
    const lower = searchTerm.toLowerCase();
    return allGroups.filter((g) => g.name.toLowerCase().includes(lower));
  }, [allGroups, searchTerm]);

  const hasChanges = useMemo(() => {
    if (memberGroupIds.size !== initialMemberGroupIds.size) return true;
    return Array.from(memberGroupIds).some(
      (id) => !initialMemberGroupIds.has(id)
    );
  }, [memberGroupIds, initialMemberGroupIds]);

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

      const promises: Promise<void>[] = [];
      for (const groupId of toAdd) {
        promises.push(addUserToGroup(groupId, user.id));
      }
      for (const groupId of toRemove) {
        const group = allGroups?.find((g) => g.id === groupId);
        if (group) {
          const currentUserIds = group.users.map((u) => u.id);
          promises.push(removeUserFromGroup(groupId, currentUserIds, user.id));
        }
      }

      await Promise.all(promises);
      onMutate();
      toast.success("Group memberships updated");
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgUsers}
          title="Edit User's Groups"
          description={`${user.personal_name ?? user.email} (${user.email})`}
          onClose={onClose}
        />
        <Modal.Body twoTone>
          <div className="flex flex-col gap-3">
            <InputTypeIn
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search groups..."
              leftSearchIcon
            />

            {groupsLoading ? (
              <Text as="p" text03 secondaryBody>
                Loading groups...
              </Text>
            ) : filteredGroups.length === 0 ? (
              <Text as="p" text03 secondaryBody>
                {searchTerm ? "No groups match your search" : "No groups found"}
              </Text>
            ) : (
              <div className="flex flex-col gap-1 max-h-[320px] overflow-y-auto">
                {filteredGroups.map((group) => {
                  const isMember = memberGroupIds.has(group.id);
                  return (
                    <button
                      key={group.id}
                      type="button"
                      onClick={() => toggleGroup(group.id)}
                      className="flex items-center justify-between gap-2 rounded-md px-3 py-2 hover:bg-background-neutral-02 transition-colors text-left"
                    >
                      <div className="flex flex-col gap-0.5">
                        <Text as="span" mainUiAction text05>
                          {group.name}
                        </Text>
                        <Text as="span" secondaryBody text03>
                          {group.users.length}{" "}
                          {group.users.length === 1 ? "member" : "members"}
                        </Text>
                      </div>
                      {isMember && <Tag title="Joined" color="green" />}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
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
