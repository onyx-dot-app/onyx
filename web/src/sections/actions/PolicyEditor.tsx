"use client";

import { useTranslations } from "next-intl";
import type { RichStr } from "@opal/types";
import { toPlainString } from "@opal/components/text/InlineMarkdown";
import { Text, InputSingleSelect } from "@opal/components";
import PolicyToggle, {
  usePolicyOptions,
} from "@/sections/actions/PolicyToggle";
import type { PolicyValue } from "@/lib/integrations/types";

export interface PolicyEditorItem {
  id: string;
  name: string;
  description: string;
  defaultPolicy: PolicyValue;
  /** Values the admin cannot choose for this item. */
  disabledPolicies?: readonly PolicyValue[];
  note?: string | RichStr;
}

interface PolicyEditorProps {
  title: string | RichStr;
  disabled?: boolean;
  onReset: () => void;
  resetLabel: string | RichStr;
  items: PolicyEditorItem[];
  policies: Record<string, PolicyValue>;
  onChange: (policies: Record<string, PolicyValue>) => void;
}

export default function PolicyEditor({
  title,
  disabled = false,
  onReset,
  resetLabel,
  items,
  policies,
  onChange,
}: PolicyEditorProps) {
  const copy = useTranslations("craft.actionPolicies");
  const editorCopy = useTranslations("actions.policyEditor");
  const options = usePolicyOptions();
  function accepts(item: PolicyEditorItem, value: PolicyValue): boolean {
    return !item.disabledPolicies?.includes(value);
  }

  return (
    <div className="flex flex-col gap-4">
      <Text font="main-ui-action">{title}</Text>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Text font="secondary-body" color="text-03">
          {editorCopy("toolCount", { count: items.length })}
        </Text>
        <div className="ms-auto w-44">
          <InputSingleSelect
            aria-label={copy("setPermissions")}
            placeholder={copy("setPermissions")}
            value=""
            disabled={disabled || items.length === 0}
            options={[
              ...options.map((option) => ({
                value: option.value,
                title: option.label,
                disabled: !items.some((item) => accepts(item, option.value)),
              })),
              {
                options: [{ value: "reset", title: toPlainString(resetLabel) }],
              },
            ]}
            onValueChange={(value) => {
              if (value === "reset") onReset();
              else if (
                value === "allow" ||
                value === "ask" ||
                value === "blocked"
              ) {
                onChange({
                  ...policies,
                  ...Object.fromEntries(
                    items
                      .filter((item) => accepts(item, value))
                      .map((item) => [item.id, value])
                  ),
                });
              }
            }}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2">
        {items.length === 0 && (
          <Text font="secondary-body" color="text-03">
            {copy("emptyActions")}
          </Text>
        )}
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
              {item.note && (
                <Text font="secondary-body" color="text-02">
                  {item.note}
                </Text>
              )}
            </div>
            <PolicyToggle
              label={item.name}
              disabled={disabled}
              disabledValues={item.disabledPolicies}
              value={policies[item.id] ?? item.defaultPolicy}
              onChange={(value) => onChange({ ...policies, [item.id]: value })}
            />
          </div>
        ))}
      </div>
    </div>
  );
}
