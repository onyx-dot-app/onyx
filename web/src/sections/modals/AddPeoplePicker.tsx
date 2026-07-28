"use client";

import { ChangeEvent, useMemo, useState } from "react";
import { Button, LineItemButton, Tag, Text } from "@opal/components";
import { SvgUser, SvgUsers, SvgX } from "@opal/icons";
import { cn } from "@opal/utils";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import type { MinimalUserSnapshot } from "@/lib/types";
import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import { SharePermissionMenu } from "@/sections/modals/SharePermissionMenu";
import {
  PERMISSION_OPTIONS,
  type ShareAccessPermission,
} from "@/sections/modals/shareAccessConstants";

interface Suggestion {
  id: string;
  label: string;
  shared: boolean;
  type: "group" | "user";
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
  const [query, setQuery] = useState("");

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

  const hasStagedItems = stagedUsers.length > 0 || stagedGroups.length > 0;
  const permissionOptions = PERMISSION_OPTIONS;

  function handleSelectSuggestion(suggestion: Suggestion) {
    if (suggestion.shared) {
      return;
    }

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
          <InputTypeIn
            clearButton
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              setQuery(event.target.value)
            }
            placeholder="Add users, groups, and accounts"
            value={query}
            variant={disabled ? "disabled" : "primary"}
          />

          {suggestions.length > 0 ? (
            <div className="absolute left-0 right-0 top-[calc(100%+0.25rem)] z-20 rounded-12 border border-border-01 bg-background-tint-00 p-1 shadow-md">
              <div className="flex flex-col gap-1">
                {suggestions.map((suggestion) => (
                  <div
                    className={cn(suggestion.shared ? "opacity-60" : undefined)}
                    key={`${suggestion.type}-${suggestion.id}`}
                  >
                    <LineItemButton
                      description={
                        suggestion.type === "group" ? "Group" : undefined
                      }
                      icon={suggestion.type === "group" ? SvgUsers : SvgUser}
                      onClick={() => handleSelectSuggestion(suggestion)}
                      rightChildren={
                        suggestion.shared ? (
                          <Tag color="gray" title="Shared" />
                        ) : null
                      }
                      rounding="md"
                      selectVariant="select-heavy"
                      sizePreset="main-ui"
                      state={suggestion.shared ? "filled" : "empty"}
                      title={suggestion.label}
                      variant="section"
                      width="full"
                    />
                  </div>
                ))}
              </div>
            </div>
          ) : null}
        </div>

        {hasStagedItems ? (
          <div className="w-40 shrink-0">
            <SharePermissionMenu
              ariaLabel="Select staged permission"
              onChange={onStagedPermissionChange}
              options={permissionOptions}
              value={stagedPermission}
              width="full"
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
