"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import type { RichStr } from "@opal/types";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import {
  Text,
  InputSingleSelect,
  InputTypeIn,
  Tooltip,
} from "@opal/components";
import PolicyToggle from "@/sections/actions/PolicyToggle";
import type { PolicyValue } from "@/lib/integrations/types";

export interface PolicyEditorItem {
  id: string;
  name: string;
  description: string;
  defaultPolicy: PolicyValue;
  editable?: boolean;
  /** Values the admin cannot choose for this item. */
  disabledPolicies?: readonly PolicyValue[];
  lockReason?: "workspace_disabled" | "workspace_managed" | null;
  note?: string | RichStr;
}

interface PolicyEditorProps {
  showTitle?: boolean;
  title?: string | RichStr;
  searchable?: boolean;
  disabled?: boolean;
  onReset?: () => void;
  resetLabel?: string | RichStr;
  items: PolicyEditorItem[];
  policies: Record<string, PolicyValue>;
  onChange?: (policies: Record<string, PolicyValue>) => void;
}

export default function PolicyEditor({
  showTitle = true,
  title,
  searchable = true,
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
  const toolCopy = useTranslations("actions.mcpTools");
  const detailCopy = useTranslations("actions.memberPlugins.detail");
  const [query, setQuery] = useState("");
  const search = query.trim().toLocaleLowerCase();
  const shownItems = items.filter((item) =>
    `${item.name} ${item.description}`.toLocaleLowerCase().includes(search)
  );
  const editableItems = shownItems.filter((item) => item.editable !== false);
  function accepts(item: PolicyEditorItem, value: PolicyValue): boolean {
    return !item.disabledPolicies?.includes(value);
  }
  const options: { value: PolicyValue; label: string }[] = [
    { value: "allow", label: policyCopy("always.label") },
    { value: "ask", label: policyCopy("ask.label") },
    { value: "blocked", label: policyCopy("deny.label") },
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
    <div className="flex flex-col gap-4">
      {showTitle && (
        <Text font="main-ui-action">{title ?? t("permissions.title")}</Text>
      )}
      {searchable && (
        <InputTypeIn
          icon="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={toolCopy("search")}
          aria-label={toolCopy("search")}
        />
      )}
      {onChange && (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Text font="secondary-body" color="text-03">
            {detailCopy("toolCount", { count: shownItems.length })}
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
                  disabled: !editableItems.some((item) =>
                    accepts(item, option.value)
                  ),
                })),
                {
                  options: [
                    {
                      value: "reset",
                      title: toPlainString(
                        resetLabel ?? t("permissions.defaultOption")
                      ),
                    },
                  ],
                },
              ]}
              onValueChange={(value) => {
                if (value === "reset") reset();
                else if (
                  value === "allow" ||
                  value === "ask" ||
                  value === "blocked"
                ) {
                  onChange({
                    ...policies,
                    ...Object.fromEntries(
                      editableItems
                        .filter((item) => accepts(item, value))
                        .map((item) => [item.id, value])
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
              {item.note && (
                <Text font="secondary-body" color="text-02">
                  {item.note}
                </Text>
              )}
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
                  disabledValues={item.disabledPolicies}
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
