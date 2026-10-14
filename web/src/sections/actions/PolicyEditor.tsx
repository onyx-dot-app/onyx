"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Text, InputSingleSelect, Collapsible } from "@opal/components";
import PolicyToggle from "@/sections/actions/PolicyToggle";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";

// One agent-callable capability whose approval policy an admin can set —
// an external-app action or an MCP tool.
export interface PolicyEditorItem {
  id: string;
  name: string;
  description: string;
  defaultPolicy: EndpointPolicy;
}

// The bulk selector collapses every item to a single policy. "CUSTOM" is a
// display-only state shown when per-item choices diverge (or any is DENY,
// which the two-option bulk control can't represent) — selecting it isn't
// possible, so the trigger falls back to its "Custom" placeholder.
type BulkPolicy = "ALWAYS" | "ASK" | "CUSTOM";

function bulkPolicyOf(
  items: PolicyEditorItem[],
  policies: Record<string, EndpointPolicy>
): BulkPolicy {
  const values = items.map((item) => policies[item.id] ?? item.defaultPolicy);
  if (values.length === 0) return "ASK";
  if (values.every((value) => value === "ALWAYS")) return "ALWAYS";
  if (values.every((value) => value === "ASK")) return "ASK";
  return "CUSTOM";
}

interface PolicyEditorProps {
  items: PolicyEditorItem[];
  policies: Record<string, EndpointPolicy>;
  onChange: (policies: Record<string, EndpointPolicy>) => void;
}

/** Approval-policy section of the editor: a bulk Auto-approve/Ask selector
 * plus an Advanced section with a per-item three-state toggle. */
export default function PolicyEditor({
  items,
  policies,
  onChange,
}: PolicyEditorProps) {
  const t = useTranslations("craft.apps.policyEditor");
  const bulkValue = bulkPolicyOf(items, policies);
  const [advancedOpen, setAdvancedOpen] = useState(bulkValue === "CUSTOM");

  // Stored choices may arrive after mount (fetched, or seeded by an effect).
  // Open "Advanced" whenever they can't be shown as a single bulk value.
  useEffect(() => {
    if (bulkValue === "CUSTOM") setAdvancedOpen(true);
  }, [bulkValue]);

  // Apply one policy to every item (the simple, non-advanced control).
  function applyBulk(policy: EndpointPolicy) {
    onChange({
      ...policies,
      ...Object.fromEntries(items.map((item) => [item.id, policy])),
    });
  }

  return (
    <div className="flex flex-col gap-2 pt-2">
      <Text font="main-ui-action">{t("permissions.title")}</Text>
      <Text font="secondary-body" color="text-03">
        {t("permissions.description")}
      </Text>

      <InputSingleSelect
        value={bulkValue === "CUSTOM" ? "" : bulkValue}
        onValueChange={(value) => {
          if (value === "ALWAYS" || value === "ASK") applyBulk(value);
        }}
        placeholder={t("permissions.customOption")}
        options={[
          { value: "ALWAYS", title: t("permissions.autoApproveOption") },
          { value: "ASK", title: t("permissions.askOption") },
        ]}
      />

      <Collapsible
        open={advancedOpen}
        onOpenChange={setAdvancedOpen}
        title={t("advanced.title")}
        description={t("advanced.description")}
      >
        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <div
              key={item.id}
              className="flex items-center justify-between gap-3"
            >
              <div className="flex flex-col">
                <Text font="main-ui-action">{item.name}</Text>
                <Text font="secondary-body" color="text-03">
                  {item.description}
                </Text>
              </div>
              <PolicyToggle
                value={policies[item.id] ?? item.defaultPolicy}
                onChange={(value) =>
                  onChange({ ...policies, [item.id]: value })
                }
              />
            </div>
          ))}
        </div>
      </Collapsible>
    </div>
  );
}
