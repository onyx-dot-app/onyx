"use client";

import { useEffect, useState } from "react";
import {
  Button,
  InputTypeIn,
  Modal,
  PasswordInputTypeIn,
  Text,
} from "@opal/components";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
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

// A required text input the app needs before it can be saved
// (name, credentials, …).
export interface EditorField {
  key: string;
  label: string;
  description: string;
  placeholder: string;
  secret: boolean;
}

interface ActionPolicyEditorModalProps {
  onClose: () => void;
  title: string;
  description: string;
  /** Shown in place of field inputs when there is nothing to type in. */
  note?: string;
  fields: EditorField[];
  initialFieldValues: Record<string, string>;
  /** Undefined while the capability list is still loading. */
  policyItems: PolicyEditorItem[] | undefined;
  initialPolicies: Record<string, EndpointPolicy>;
  /** Shown when the capability list resolves to empty. */
  emptyPoliciesMessage: string;
  saveLabel: string;
  /** Persist the edit; throw to surface the failure inside the modal. */
  onSave: (
    fieldValues: Record<string, string>,
    policies: Record<string, EndpointPolicy>
  ) => Promise<void>;
  bodyAfterPolicies?: (
    saveWithoutClosing: () => Promise<boolean>
  ) => React.ReactNode;
  /** Keep the modal mounted when save advances its caller to another step. */
  closeAfterSave?: boolean;
}

/** The one edit dialog for everything the Craft agent can be granted.
 * Callers (external apps, MCP servers) normalize their data into fields +
 * policy items and supply the save call; the UI is identical for both.
 * Mount it only while open — initial values are read once. */
export default function ActionPolicyEditorModal({
  onClose,
  title,
  description,
  note,
  fields,
  initialFieldValues,
  policyItems,
  initialPolicies,
  emptyPoliciesMessage,
  saveLabel,
  onSave,
  bodyAfterPolicies,
  closeAfterSave = true,
}: ActionPolicyEditorModalProps) {
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({
    ...initialFieldValues,
  });
  const [policies, setPolicies] = useState<Record<string, EndpointPolicy>>({
    ...initialPolicies,
  });
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldsFilled = fields.every(
    (field) => (fieldValues[field.key] ?? "").trim().length > 0
  );
  const canSave = fieldsFilled && policyItems !== undefined && !isSaving;

  async function persist(): Promise<boolean> {
    setIsSaving(true);
    setError(null);
    try {
      await onSave(fieldValues, policies);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function save() {
    if ((await persist()) && closeAfterSave) onClose();
  }

  return (
    <Modal open onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header title={title} description={description} />
        <Modal.Body>
          <div className="flex flex-col gap-3">
            {note && (
              <Text font="secondary-body" color="text-03">
                {note}
              </Text>
            )}

            {fields.map((field) => {
              const Input = field.secret ? PasswordInputTypeIn : InputTypeIn;
              return (
                <div key={field.key} className="flex flex-col gap-1">
                  <Text font="main-ui-action">{field.label}</Text>
                  <Input
                    value={fieldValues[field.key] ?? ""}
                    onChange={(e) =>
                      setFieldValues((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    placeholder={field.placeholder}
                  />
                  <Text font="secondary-body" color="text-03">
                    {field.description}
                  </Text>
                </div>
              );
            })}

            {policyItems === undefined ? (
              <Text font="main-content-body" color="text-03">
                Loading…
              </Text>
            ) : policyItems.length === 0 ? (
              <Text font="secondary-body" color="text-03">
                {emptyPoliciesMessage}
              </Text>
            ) : (
              <PolicyEditor
                items={policyItems}
                policies={policies}
                onChange={setPolicies}
              />
            )}

            {bodyAfterPolicies?.(persist)}

            {error && (
              <Text font="secondary-body" color="text-03">
                {error}
              </Text>
            )}
          </div>
        </Modal.Body>
        <Modal.Footer>
          <div className="flex justify-end gap-2 w-full">
            <Button
              prominence="secondary"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button onClick={save} disabled={!canSave}>
              {isSaving ? "Saving…" : saveLabel}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}

// ── Policy editor ──────────────────────────────────────────────────────

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
function PolicyEditor({ items, policies, onChange }: PolicyEditorProps) {
  const bulkValue = bulkPolicyOf(items, policies);
  const [advancedOpen, setAdvancedOpen] = useState(bulkValue === "CUSTOM");

  // Stored choices may arrive after mount (fetched, or seeded by an effect).
  // Open "Advanced" whenever they can't be shown as a single bulk value.
  useEffect(() => {
    if (bulkValue === "CUSTOM") setAdvancedOpen(true);
  }, [bulkValue]);

  // Apply one policy to every item (the simple, non-advanced control).
  function applyBulk(policy: EndpointPolicy) {
    onChange(Object.fromEntries(items.map((item) => [item.id, policy])));
  }

  return (
    <div className="flex flex-col gap-2 pt-2">
      <Text font="main-ui-action">Permissions</Text>
      <Text font="secondary-body" color="text-03">
        Choose what the agent may do. “Ask” prompts you in chat before each
        action runs; “Auto-approve” lets it run without prompting. Use Advanced
        to set a policy per action.
      </Text>

      <InputSelect
        value={bulkValue}
        onValueChange={(value) => {
          if (value === "ALWAYS" || value === "ASK") applyBulk(value);
        }}
      >
        <InputSelect.Trigger placeholder="Custom" />
        <InputSelect.Content>
          <InputSelect.Item value="ALWAYS">Auto-approve</InputSelect.Item>
          <InputSelect.Item value="ASK">Ask</InputSelect.Item>
        </InputSelect.Content>
      </InputSelect>

      <SimpleCollapsible open={advancedOpen} onOpenChange={setAdvancedOpen}>
        <SimpleCollapsible.Header
          title="Advanced"
          description="Set a policy for each action individually."
        />
        <SimpleCollapsible.Content>
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
        </SimpleCollapsible.Content>
      </SimpleCollapsible>
    </div>
  );
}
