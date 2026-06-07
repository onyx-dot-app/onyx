"use client";

import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { InputTypeIn } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import SimpleCollapsible from "@/refresh-components/SimpleCollapsible";
import {
  BuiltInExternalAppDescriptor,
  EndpointDescriptor,
  EndpointPolicy,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import {
  createBuiltInExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";

const POLICY_OPTIONS: { value: EndpointPolicy; label: string }[] = [
  { value: "ALWAYS", label: "Auto-approve" },
  { value: "ASK", label: "Ask" },
  { value: "DENY", label: "Deny" },
];

interface PolicyToggleProps {
  value: EndpointPolicy;
  onChange: (value: EndpointPolicy) => void;
}

function PolicyToggle({ value, onChange }: PolicyToggleProps) {
  return (
    <div className="flex gap-1 shrink-0">
      {POLICY_OPTIONS.map((option) => (
        <Button
          key={option.value}
          size="xs"
          prominence={value === option.value ? "primary" : "tertiary"}
          onClick={() => onChange(option.value)}
        >
          {option.label}
        </Button>
      ))}
    </div>
  );
}

// The bulk selector collapses every action to a single policy. "CUSTOM" is a
// display-only state shown when per-action choices diverge (or any is DENY,
// which the two-option bulk control can't represent) — selecting it isn't
// possible, so the trigger falls back to its "Custom" placeholder.
type BulkPolicy = "ALWAYS" | "ASK" | "CUSTOM";

function bulkPolicyOf(
  actions: EndpointDescriptor[],
  policies: Record<string, EndpointPolicy>
): BulkPolicy {
  const values = actions.map(
    (action) => policies[action.action_id] ?? action.default_policy
  );
  if (values.length === 0) return "ASK";
  if (values.every((value) => value === "ALWAYS")) return "ALWAYS";
  if (values.every((value) => value === "ASK")) return "ASK";
  return "CUSTOM";
}

interface ConfigureProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  descriptor: BuiltInExternalAppDescriptor;
  /** Null → create new instance; non-null → edit existing row. */
  existingApp: ExternalAppAdminResponse | null;
}

export default function ConfigureProviderModal({
  open,
  onClose,
  onSaved,
  descriptor,
  existingApp,
}: ConfigureProviderModalProps) {
  const [name, setName] = useState("");
  const [credentialValues, setCredentialValues] = useState<
    Record<string, string>
  >({});
  const [policies, setPolicies] = useState<Record<string, EndpointPolicy>>({});
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Managed built-ins (cloud): Onyx owns creds/config, so the modal only edits
  // policies — cred fields are hidden and the backend ignores them anyway.
  const managed = existingApp?.is_onyx_managed ?? false;

  // Re-seed every time the modal opens so admins can tweak one
  // field without re-entering the rest.
  useEffect(() => {
    if (!open) return;
    setName(existingApp?.name ?? descriptor.name);
    const initial: Record<string, string> = {};
    for (const field of descriptor.required_org_credential_fields) {
      initial[field.key] =
        existingApp?.organization_credentials[field.key] ?? "";
    }
    setCredentialValues(initial);

    // Seed each action from the admin's stored choice (edit) or the action's
    // backend-declared default (create) — usually "Ask", but a provider can
    // declare a different out-of-the-box stance per action.
    const storedState: Record<string, EndpointPolicy> = {};
    for (const action of existingApp?.actions ?? []) {
      storedState[action.action_id] = action.state;
    }
    const seededPolicies: Record<string, EndpointPolicy> = {};
    for (const action of descriptor.actions) {
      seededPolicies[action.action_id] =
        storedState[action.action_id] ?? action.default_policy;
    }
    setPolicies(seededPolicies);
    // Open "Advanced" up front only when the stored choices can't be shown as a
    // single bulk value (mixed, or containing a Deny).
    setAdvancedOpen(
      bulkPolicyOf(descriptor.actions, seededPolicies) === "CUSTOM"
    );
    setError(null);
  }, [open, descriptor, existingApp]);

  const nameFilled = name.trim().length > 0;
  const credsFilled = descriptor.required_org_credential_fields.every(
    (f) => (credentialValues[f.key] ?? "").trim().length > 0
  );
  // Managed apps only edit policies, so name/credentials aren't required.
  const canSave = managed ? !isSaving : nameFilled && credsFilled && !isSaving;

  const bulkValue = bulkPolicyOf(descriptor.actions, policies);

  // Apply one policy to every action (the simple, non-advanced control).
  function applyBulk(policy: EndpointPolicy) {
    setPolicies(
      Object.fromEntries(
        descriptor.actions.map((action) => [action.action_id, policy])
      )
    );
  }

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      if (managed && existingApp) {
        // Managed: only policies are persisted; a partial PATCH leaves the rest.
        await updateExternalApp(existingApp.id, {
          action_policies: policies,
        });
      } else if (existingApp) {
        // Merge creds so non-credential metadata survives a credential edit.
        await updateExternalApp(existingApp.id, {
          name: name.trim(),
          description: descriptor.description,
          upstream_url_patterns: descriptor.upstream_url_patterns,
          auth_template: descriptor.auth_template,
          organization_credentials: {
            ...existingApp.organization_credentials,
            ...credentialValues,
          },
          // Saving credentials implies enable; disable is separate.
          enabled: true,
          action_policies: policies,
        });
      } else {
        await createBuiltInExternalApp({
          name: name.trim(),
          description: descriptor.description,
          app_type: descriptor.app_type,
          upstream_url_patterns: descriptor.upstream_url_patterns,
          auth_template: descriptor.auth_template,
          organization_credentials: credentialValues,
          enabled: true,
          action_policies: policies,
        });
      }
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  }

  const headerTitle = existingApp
    ? `Edit ${existingApp.name}`
    : `Add ${descriptor.name}`;

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={headerTitle}
          description={
            managed
              ? "Provided by Onyx — configure what the agent may do."
              : descriptor.setup_instructions
          }
        />
        <Modal.Body>
          <div className="flex flex-col gap-3">
            {managed ? (
              <Text font="secondary-body" color="text-03">
                This app is provided by Onyx — credentials are managed for you.
                Enable it from the apps list, then choose what the agent may do
                below.
              </Text>
            ) : (
              <>
                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">Name</Text>
                  <InputTypeIn
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={descriptor.name}
                  />
                  <Text font="secondary-body" color="text-03">
                    {`A label for this connection. Use a distinct name when adding multiple instances of the same provider (e.g. "${descriptor.name} — Engineering").`}
                  </Text>
                </div>

                {descriptor.required_org_credential_fields.map((field) => {
                  const Input = field.secret
                    ? PasswordInputTypeIn
                    : InputTypeIn;
                  return (
                    <div key={field.key} className="flex flex-col gap-1">
                      <Text font="main-ui-action">{field.label}</Text>
                      <Input
                        value={credentialValues[field.key] ?? ""}
                        onChange={(e) =>
                          setCredentialValues((prev) => ({
                            ...prev,
                            [field.key]: e.target.value,
                          }))
                        }
                        placeholder={field.label}
                      />
                      <Text font="secondary-body" color="text-03">
                        {field.description}
                      </Text>
                    </div>
                  );
                })}
              </>
            )}

            {descriptor.actions.length > 0 && (
              <div className="flex flex-col gap-2 pt-2">
                <Text font="main-ui-action">Permissions</Text>
                <Text font="secondary-body" color="text-03">
                  Choose what the agent may do with this app. “Ask” prompts you
                  in chat before each action runs; “Auto-approve” lets it run
                  without prompting. Use Advanced to set a policy per action.
                </Text>

                <InputSelect
                  value={bulkValue}
                  onValueChange={(value) => {
                    if (value === "ALWAYS" || value === "ASK") applyBulk(value);
                  }}
                >
                  <InputSelect.Trigger placeholder="Custom" />
                  <InputSelect.Content>
                    <InputSelect.Item value="ALWAYS">
                      Auto-approve
                    </InputSelect.Item>
                    <InputSelect.Item value="ASK">Ask</InputSelect.Item>
                  </InputSelect.Content>
                </InputSelect>

                <SimpleCollapsible
                  open={advancedOpen}
                  onOpenChange={setAdvancedOpen}
                >
                  <SimpleCollapsible.Header
                    title="Advanced"
                    description="Set a policy for each action individually."
                  />
                  <SimpleCollapsible.Content>
                    <div className="flex flex-col gap-2">
                      {descriptor.actions.map((action) => (
                        <div
                          key={action.action_id}
                          className="flex items-center justify-between gap-3"
                        >
                          <div className="flex flex-col">
                            <Text font="main-ui-action">
                              {action.normalised_name}
                            </Text>
                            <Text font="secondary-body" color="text-03">
                              {action.description}
                            </Text>
                          </div>
                          <PolicyToggle
                            value={
                              policies[action.action_id] ??
                              action.default_policy
                            }
                            onChange={(value) =>
                              setPolicies((prev) => ({
                                ...prev,
                                [action.action_id]: value,
                              }))
                            }
                          />
                        </div>
                      ))}
                    </div>
                  </SimpleCollapsible.Content>
                </SimpleCollapsible>
              </div>
            )}
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
              {isSaving ? "Saving…" : existingApp ? "Save" : "Add"}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
