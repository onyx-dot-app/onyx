"use client";

import { useEffect, useMemo, useState } from "react";
import InputComboBox from "@/refresh-components/inputs/InputComboBox";
import { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import { PersonaOwnerGroup } from "@/lib/agents/types";
import { MinimalUserSnapshot } from "@/lib/types";
import { Tag, Text } from "@opal/components";
import { SvgUser, SvgUsers } from "@opal/icons";

export type TransferOwnershipTarget =
  | {
      label: string;
      type: "group";
      value: `group-${number}`;
    }
  | {
      label: string;
      type: "user";
      value: `user-${string}`;
    }
  | null;

export interface TransferOwnershipViewProps {
  agent: {
    owner: MinimalUserSnapshot | null;
    owner_group?: PersonaOwnerGroup | null;
  } | null;
  groups: MinimalUserGroupSnapshot[];
  onSelectedTargetChange: (target: TransferOwnershipTarget) => void;
  selectedTarget: TransferOwnershipTarget;
  users: MinimalUserSnapshot[];
}

export function TransferOwnershipView({
  agent,
  groups,
  onSelectedTargetChange,
  selectedTarget,
  users,
}: TransferOwnershipViewProps) {
  const [inputValue, setInputValue] = useState("");

  useEffect(() => {
    // Only sync the field when a real selection arrives. A null target comes
    // from the user typing to change the selection, where their input must stand.
    if (selectedTarget) {
      setInputValue(selectedTarget.label);
    }
  }, [selectedTarget]);

  const options = useMemo(() => {
    const ownerUserId = agent?.owner?.id;
    const ownerGroupId = agent?.owner_group?.id;

    const userOptions = users.map((user) => ({
      value: `user-${user.id}`,
      label: user.email,
      description: ownerUserId === user.id ? "Current Owner" : undefined,
      disabled: ownerUserId === user.id,
    }));

    const groupOptions = groups.map((group) => ({
      value: `group-${group.id}`,
      label: group.name,
      description: ownerGroupId === group.id ? "Current Owner" : undefined,
      disabled: ownerGroupId === group.id,
    }));

    return [...userOptions, ...groupOptions];
  }, [agent?.owner?.id, agent?.owner_group?.id, groups, users]);

  function handleValueChange(value: string) {
    const selectedOption = options.find((option) => option.value === value);
    if (!selectedOption) {
      onSelectedTargetChange(null);
      return;
    }

    if (value.startsWith("user-")) {
      onSelectedTargetChange({
        label: selectedOption.label,
        type: "user",
        value: value as `user-${string}`,
      });
      return;
    }

    onSelectedTargetChange({
      label: selectedOption.label,
      type: "group",
      value: value as `group-${number}`,
    });
  }

  return (
    <div className="flex w-full flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Text color="text-03" font="secondary-body">
          Transfer Ownership To
        </Text>

        <InputComboBox
          onChange={(event) => {
            setInputValue(event.target.value);
            onSelectedTargetChange(null);
          }}
          onValueChange={handleValueChange}
          options={options}
          placeholder="Add a user or group"
          strict
          value={inputValue}
        />
      </div>

      {selectedTarget ? (
        <div className="flex items-center justify-between rounded-12 border border-border-01 bg-background-tint-00 px-3 py-2">
          <div className="flex items-center gap-2">
            {selectedTarget.type === "group" ? (
              <SvgUsers className="h-4 w-4 stroke-text-03" />
            ) : (
              <SvgUser className="h-4 w-4 stroke-text-03" />
            )}

            <Text color="text-04" font="main-ui-body">
              {selectedTarget.label}
            </Text>
          </div>

          {selectedTarget.type === "group" ? (
            <Tag color="gray" title="Group" />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
