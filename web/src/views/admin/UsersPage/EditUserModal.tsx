"use client";

import { useState, useMemo, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider } from "@opal/components";
import { SvgUsers, SvgUser, SvgLogOut, SvgCheck } from "@opal/icons";
import { ContentAction, toast } from "@opal/layouts";
import { Modal } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import { Popover } from "@opal/components";
import LineItem from "@/refresh-components/buttons/LineItem";
import { ShadowDiv } from "@opal/components";
import { Tooltip } from "@opal/components";
import { Section } from "@/layouts/general-layouts";
import useGroups from "@/hooks/useGroups";
import { addUserToGroup, removeUserFromGroup } from "./svc";
import type { UserRow } from "./interfaces";
import { cn } from "@opal/utils";

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
  const t = useTranslations("admin.users");
  // defaults included; backend rejects the unsafe removals (last admin, self)
  const { data: allGroups, isLoading: groupsLoading } = useGroups(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [popoverOpen, setPopoverOpen] = useState(false);

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

  const hasChanges = hasGroupChanges;

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

      onMutate();
      toast.success(t("editModal.toasts.updated"));
      onClose();
    } catch (err) {
      onMutate(); // refresh to show partially-applied state
      toast.error(
        err instanceof Error ? err.message : t("editModal.toasts.error")
      );
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
          title={t("editModal.title")}
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
              gap={2}
              padding={1}
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
                      placeholder={t("editModal.search.placeholder")}
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
                    <LineItem
                      skeleton
                      description={t("editModal.groupList.loading.description")}
                    >
                      {t("editModal.groupList.loading.title")}
                    </LineItem>
                  ) : dropdownGroups.length === 0 ? (
                    <LineItem
                      skeleton
                      description={t(
                        "editModal.groupList.noResults.description"
                      )}
                    >
                      {t("editModal.groupList.noResults.title")}
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
                            description={t("editModal.groupList.memberCount", {
                              count: group.users.length,
                            })}
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
                    description={t("editModal.joinedGroups.empty.description", {
                      name: displayName,
                    })}
                  >
                    {t("editModal.joinedGroups.empty.title")}
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
                        description={t("editModal.groupList.memberCount", {
                          count: group.users.length,
                        })}
                        rightChildren={
                          <Tooltip
                            tooltip={t("editModal.removeGroupButton.tooltip")}
                            side="left"
                          >
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
          </Section>
        </Modal.Body>

        <Modal.Footer>
          <Button
            prominence="secondary"
            onClick={isSubmitting ? undefined : onClose}
          >
            {t("editModal.cancelButton.label")}
          </Button>
          <Button disabled={isSubmitting || !hasChanges} onClick={handleSave}>
            {t("editModal.saveButton.label")}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
