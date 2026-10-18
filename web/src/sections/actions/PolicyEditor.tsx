"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import {
  Text,
  InputSingleSelect,
  InputTypeIn,
  InputSwitch,
  Tooltip,
} from "@opal/components";
import PolicyToggle from "@/sections/actions/PolicyToggle";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

export interface PolicyEditorItem {
  id: string;
  name: string;
  description: string;
  defaultPolicy: ActionPolicy;
  editable?: boolean;
  lockReason?: "workspace_disabled" | "workspace_managed" | null;
}

interface PolicyEditorProps {
  showTitle?: boolean;
  showDescription?: boolean;
  disabled?: boolean;
  onReset?: () => void;
  resetLabel?: string;
  items: PolicyEditorItem[];
  policies: Record<string, ActionPolicy>;
  onChange?: (policies: Record<string, ActionPolicy>) => void;
}

export default function PolicyEditor({
  showTitle = true,
  showDescription = true,
  disabled = false,
  onReset,
  resetLabel,
  items,
  policies,
  onChange,
}: PolicyEditorProps) {
  const t = useTranslations("craft.apps.policyEditor");
  const copy = useTranslations("craft.actionPolicies");
  const policyCopy = useTranslations("actions.policyToggle");
  const [query, setQuery] = useState("");
  const search = query.trim().toLocaleLowerCase();
  const shownItems = items.filter((item) =>
    `${item.name} ${item.description}`.toLocaleLowerCase().includes(search)
  );
  const editableItems = shownItems.filter((item) => item.editable !== false);
  const options: { value: ActionPolicy; label: string }[] = [
    { value: "ALWAYS", label: policyCopy("always.label") },
    { value: "ASK", label: policyCopy("ask.label") },
    { value: "DENY", label: policyCopy("deny.label") },
  ];
  function reset() {
    if (onReset) onReset();
    else
      onChange?.({
        ...policies,
        ...Object.fromEntries(
          items
            .filter((item) => item.editable !== false)
            .map((item) => [item.id, item.defaultPolicy])
        ),
      });
  }

  return (
    <div className="flex flex-col gap-2 pt-2">
      {showTitle && <Text font="main-ui-action">{t("permissions.title")}</Text>}
      {showDescription && (
        <Text font="secondary-body" color="text-03">
          {t("permissions.description")}
        </Text>
      )}

      <InputTypeIn
        searchIcon
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder={copy("searchActions")}
        aria-label={copy("searchActions")}
      />
      {onChange && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Text font="secondary-body" color="text-03">
            {copy("applyMatching", { count: editableItems.length })}
          </Text>
          <div className="ms-auto w-44">
            <InputSingleSelect
              aria-label={copy("setPermissions")}
              placeholder={copy("setPermissions")}
              value=""
              disabled={
                disabled || !items.some((item) => item.editable !== false)
              }
              options={[
                ...options.map((option) => ({
                  value: option.value,
                  title: option.label,
                  disabled: editableItems.length === 0,
                })),
                {
                  options: [
                    {
                      value: "reset",
                      title: resetLabel ?? t("permissions.defaultOption"),
                    },
                  ],
                },
              ]}
              onValueChange={(value) => {
                if (value === "reset") reset();
                else if (
                  value === "ALWAYS" ||
                  value === "ASK" ||
                  value === "DENY"
                ) {
                  onChange({
                    ...policies,
                    ...Object.fromEntries(
                      editableItems.map((item) => [item.id, value])
                    ),
                  });
                }
              }}
            />
          </div>
        </div>
      )}

      <div className="flex flex-col gap-2">
        {shownItems.length === 0 && (
          <Text font="secondary-body" color="text-03">
            {copy(items.length ? "noMatchingActions" : "emptyActions")}
          </Text>
        )}
        {shownItems.map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between gap-3"
          >
            <div className="flex min-w-0 flex-1 flex-col">
              <Text font="main-ui-action" wordWrap="wrap-anywhere">
                {item.name}
              </Text>
              <Text
                font="secondary-body"
                color="text-03"
                wordWrap="wrap-anywhere"
              >
                {item.description}
              </Text>
            </div>
            <Tooltip
              tooltip={
                item.lockReason === "workspace_disabled"
                  ? copy("workspaceDisabledTooltip")
                  : item.lockReason
                    ? copy(item.lockReason)
                    : undefined
              }
            >
              <div>
                <PolicyToggle
                  label={item.name}
                  disabled={disabled || !onChange || item.editable === false}
                  value={
                    item.editable === false
                      ? item.defaultPolicy
                      : (policies[item.id] ?? item.defaultPolicy)
                  }
                  onChange={(value) =>
                    onChange?.({ ...policies, [item.id]: value })
                  }
                />
              </div>
            </Tooltip>
          </div>
        ))}
      </div>
    </div>
  );
}

interface UserManagementSwitchProps {
  value: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}
export function UserManagementSwitch({
  value,
  onChange,
  disabled = false,
}: UserManagementSwitchProps) {
  const t = useTranslations("craft.actionPolicies");
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex flex-col">
        <Text font="main-ui-action">{t("userManagement")}</Text>
        <Text font="secondary-body" color="text-03">
          {t("userManagementDescription")}
        </Text>
      </div>
      <InputSwitch
        disabled={disabled}
        checked={value}
        onCheckedChange={onChange}
        aria-label={t("userManagement")}
      />
    </div>
  );
}
