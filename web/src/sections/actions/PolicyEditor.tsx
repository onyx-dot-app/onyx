"use client";

import { useTranslations } from "next-intl";
import { Text, InputSingleSelect } from "@opal/components";
import PolicyToggle from "@/sections/actions/PolicyToggle";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

export interface PolicyEditorItem {
  id: string;
  name: string;
  description: string;
  defaultPolicy: ActionPolicy;
}

type BulkPolicy = "DEFAULT" | "ALWAYS" | "ASK" | "CUSTOM";

function bulkPolicyOf(
  items: PolicyEditorItem[],
  policies: Record<string, ActionPolicy>
): BulkPolicy {
  if (
    items.every(
      (item) => (policies[item.id] ?? item.defaultPolicy) === item.defaultPolicy
    )
  )
    return "DEFAULT";
  const values = items.map((item) => policies[item.id] ?? item.defaultPolicy);
  if (values.every((value) => value === "ALWAYS")) return "ALWAYS";
  if (values.every((value) => value === "ASK")) return "ASK";
  return "CUSTOM";
}

interface PolicyEditorProps {
  showTitle?: boolean;
  items: PolicyEditorItem[];
  policies: Record<string, ActionPolicy>;
  onChange: (policies: Record<string, ActionPolicy>) => void;
}

export default function PolicyEditor({
  showTitle = true,
  items,
  policies,
  onChange,
}: PolicyEditorProps) {
  const t = useTranslations("craft.apps.policyEditor");
  const bulkValue = bulkPolicyOf(items, policies);

  function applyBulk(policy: "DEFAULT" | "ALWAYS" | "ASK") {
    onChange({
      ...policies,
      ...Object.fromEntries(
        items.map((item) => [
          item.id,
          policy === "DEFAULT" ? item.defaultPolicy : policy,
        ])
      ),
    });
  }

  return (
    <div className="flex flex-col gap-2 pt-2">
      {showTitle && <Text font="main-ui-action">{t("permissions.title")}</Text>}
      <Text font="secondary-body" color="text-03">
        {t("permissions.description")}
      </Text>

      <InputSingleSelect
        aria-label={t("permissions.title")}
        value={bulkValue}
        onValueChange={(value) => {
          if (value === "DEFAULT" || value === "ALWAYS" || value === "ASK")
            applyBulk(value);
        }}
        defaultOption="DEFAULT"
        placeholder={t("permissions.title")}
        options={[
          { value: "DEFAULT", title: t("permissions.defaultOption") },
          ...(bulkValue === "CUSTOM"
            ? [{ value: "CUSTOM", title: t("permissions.customOption") }]
            : []),
          { value: "ALWAYS", title: t("permissions.autoApproveOption") },
          { value: "ASK", title: t("permissions.askOption") },
        ]}
      />

      <div className="flex flex-col gap-2">
        {items.map((item) => (
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
            <PolicyToggle
              value={policies[item.id] ?? item.defaultPolicy}
              onChange={(value) => onChange({ ...policies, [item.id]: value })}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
