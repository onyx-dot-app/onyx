"use client";

import { ChangeEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  type DropdownItem,
  InputTypeIn,
  Text,
} from "@opal/components";
import { SvgUser, SvgUsers, SvgX } from "@opal/icons";
import type { MinimalUserSnapshot } from "@/lib/types";
import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import { SharePermissionMenu } from "@/lib/permissions/components";
import {
  type ShareAccessPermission,
  useSharePermissionOptions,
} from "@/sections/modals/shareAccessConstants";

interface Suggestion {
  id: string;
  label: string;
  shared: boolean;
  type: "group" | "user";
}

const NO_SELECTION: ReadonlySet<string> = new Set();

function suggestionValue(suggestion: Suggestion): string {
  return `${suggestion.type}-${suggestion.id}`;
}

export interface AddPeoplePickerProps {
  disabled?: boolean;
  existingGroupIds: Set<number>;
  existingUserIds: Set<string>;
  groups: MinimalUserGroupSnapshot[];
  onAddGroup: (group: MinimalUserGroupSnapshot) => void;
  onAddUser: (user: MinimalUserSnapshot) => void;
  onRemoveGroup: (groupId: number) => void;
  onRemoveUser: (userId: string) => void;
  onStagedPermissionChange: (permission: ShareAccessPermission) => void;
  stagedGroups: MinimalUserGroupSnapshot[];
  stagedPermission: ShareAccessPermission;
  stagedUsers: MinimalUserSnapshot[];
  users: MinimalUserSnapshot[];
}

export function AddPeoplePicker({
  disabled = false,
  existingGroupIds,
  existingUserIds,
  groups,
  onAddGroup,
  onAddUser,
  onRemoveGroup,
  onRemoveUser,
  onStagedPermissionChange,
  stagedGroups,
  stagedPermission,
  stagedUsers,
  users,
}: AddPeoplePickerProps) {
  const t = useTranslations("chat.modals.share");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const stagedUserIds = useMemo(
    () => new Set(stagedUsers.map((user) => user.id)),
    [stagedUsers]
  );
  const stagedGroupIds = useMemo(
    () => new Set(stagedGroups.map((group) => group.id)),
    [stagedGroups]
  );

  const suggestions = useMemo((): Suggestion[] => {
    const trimmedQuery = query.trim().toLowerCase();
    if (!trimmedQuery) {
      return [];
    }

    const userSuggestions = users
      .filter((user) => user.email.toLowerCase().includes(trimmedQuery))
      .filter((user) => !stagedUserIds.has(user.id))
      .map((user) => ({
        id: user.id,
        label: user.email,
        shared: existingUserIds.has(user.id),
        type: "user" as const,
      }));

    const groupSuggestions = groups
      .filter((group) => group.name.toLowerCase().includes(trimmedQuery))
      .filter((group) => !stagedGroupIds.has(group.id))
      .map((group) => ({
        id: String(group.id),
        label: group.name,
        shared: existingGroupIds.has(group.id),
        type: "group" as const,
      }));

    return [...userSuggestions, ...groupSuggestions].slice(0, 8);
  }, [
    existingGroupIds,
    existingUserIds,
    groups,
    query,
    stagedGroupIds,
    stagedUserIds,
    users,
  ]);

  const suggestionItems = suggestions.map(
    (suggestion): DropdownItem => ({
      kind: "option",
      value: suggestionValue(suggestion),
      title: suggestion.label,
      icon: suggestion.type === "group" ? SvgUsers : SvgUser,
      description:
        suggestion.type === "group"
          ? t("addPeople.groupSuggestion.description")
          : undefined,
      disabled: suggestion.shared,
      tag: suggestion.shared
        ? { color: "default", title: t("addPeople.sharedTag.label") }
        : undefined,
    })
  );

  const hasStagedItems = stagedUsers.length > 0 || stagedGroups.length > 0;
  const permissionOptions = useSharePermissionOptions();

  function handleSelectSuggestion(suggestion: Suggestion) {
    if (suggestion.type === "user") {
      const user = users.find(
        (shareableUser) => shareableUser.id === suggestion.id
      );
      if (user) {
        onAddUser(user);
      }
    } else {
      const group = groups.find(
        (shareableGroup) => shareableGroup.id === Number(suggestion.id)
      );
      if (group) {
        onAddGroup(group);
      }
    }

    setQuery("");
  }

  return (
    <div className="flex w-full flex-col gap-2">
      {hasStagedItems ? (
        <div className="flex flex-wrap gap-2">
          {stagedUsers.map((user) => (
            <div
              className="flex items-center gap-1 rounded-08 bg-background-tint-02 px-2 py-1"
              key={user.id}
            >
              <SvgUser className="h-4 w-4 stroke-text-03" />
              <Text color="text-04" font="main-ui-body">
                {user.email}
              </Text>
              <Button
                icon={SvgX}
                onClick={() => onRemoveUser(user.id)}
                prominence="tertiary"
                size="2xs"
              />
            </div>
          ))}

          {stagedGroups.map((group) => (
            <div
              className="flex items-center gap-1 rounded-08 bg-background-tint-02 px-2 py-1"
              key={group.id}
            >
              <SvgUsers className="h-4 w-4 stroke-text-03" />
              <Text color="text-04" font="main-ui-body">
                {group.name}
              </Text>
              <Button
                icon={SvgX}
                onClick={() => onRemoveGroup(group.id)}
                prominence="tertiary"
                size="2xs"
              />
            </div>
          ))}
        </div>
      ) : null}

      <div className="flex items-start gap-2">
        <div className="relative min-w-0 flex-1">
          <Dropdown
            open={open && suggestions.length > 0}
            onOpenChange={setOpen}
            disabled={disabled}
          >
            <Dropdown.Trigger asChild typeIn behavior="open">
              <InputTypeIn
                clearButton
                onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  setQuery(event.target.value);
                  setOpen(true);
                }}
                placeholder={t("addPeople.searchInput.placeholder")}
                aria-label={t("addPeople.searchInput.placeholder")}
                value={query}
                variant={disabled ? "disabled" : "primary"}
              />
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("addPeople.searchInput.placeholder")}
              values={NO_SELECTION}
              closeOnSelect
              onSelect={(option) => {
                const suggestion = suggestions.find(
                  (candidate) => suggestionValue(candidate) === option.value
                );
                if (suggestion) handleSelectSuggestion(suggestion);
              }}
              items={suggestionItems}
            />
          </Dropdown>
        </div>

        {hasStagedItems ? (
          <div className="w-40 shrink-0">
            <SharePermissionMenu
              ariaLabel={t("addPeople.permissionMenu.ariaLabel")}
              onChange={onStagedPermissionChange}
              options={permissionOptions}
              value={stagedPermission}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
