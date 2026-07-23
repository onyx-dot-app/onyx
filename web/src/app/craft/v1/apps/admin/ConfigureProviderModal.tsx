"use client";

import ActionPolicyEditorModal, {
  EditorField,
} from "@/app/craft/v1/apps/admin/ActionPolicyEditorModal";
import {
  BuiltInExternalAppDescriptor,
  EndpointPolicy,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import {
  createBuiltInExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";

// Field key for the instance name; prefixed so it can never collide with a
// descriptor-declared credential key.
const NAME_KEY = "__name";

interface ConfigureProviderModalProps {
  onClose: () => void;
  onSaved: () => void;
  descriptor: BuiltInExternalAppDescriptor;
  /** Null → create new instance; non-null → edit existing row. */
  existingApp: ExternalAppAdminResponse | null;
}

/** Create/edit dialog for a built-in external-app provider: maps the
 * descriptor's credential fields and actions into the shared editor. */
export default function ConfigureProviderModal({
  onClose,
  onSaved,
  descriptor,
  existingApp,
}: ConfigureProviderModalProps) {
  // Managed built-ins (cloud): Onyx owns creds/config, so the modal only edits
  // policies — cred fields are hidden and the backend ignores them anyway.
  const managed = existingApp?.is_onyx_managed ?? false;

  const fields: EditorField[] = managed
    ? []
    : [
        {
          key: NAME_KEY,
          label: "Name",
          description: `A label for this connection. Use a distinct name when adding multiple instances of the same provider (e.g. "${descriptor.name} — Engineering").`,
          placeholder: descriptor.name,
          secret: false,
        },
        ...descriptor.required_org_credential_fields.map((field) => ({
          key: field.key,
          label: field.label,
          description: field.description,
          placeholder: field.label,
          secret: field.secret,
        })),
      ];

  const initialFieldValues: Record<string, string> = {
    [NAME_KEY]: existingApp?.name ?? descriptor.name,
  };
  for (const field of descriptor.required_org_credential_fields) {
    initialFieldValues[field.key] =
      existingApp?.organization_credentials[field.key] ?? "";
  }

  // Seed each action from the admin's stored choice (edit) or the action's
  // backend-declared default (create) — usually "Ask", but a provider can
  // declare a different out-of-the-box stance per action.
  const storedPolicies: Record<string, EndpointPolicy> = {};
  for (const action of existingApp?.actions ?? []) {
    storedPolicies[action.action_id] = action.state;
  }
  const initialPolicies = Object.fromEntries(
    descriptor.actions.map((action): [string, EndpointPolicy] => [
      action.action_id,
      storedPolicies[action.action_id] ?? action.default_policy,
    ])
  );

  async function save(
    values: Record<string, string>,
    policies: Record<string, EndpointPolicy>
  ) {
    if (managed && existingApp) {
      // Managed: only policies are persisted; a partial PATCH leaves the rest.
      await updateExternalApp(existingApp.id, { action_policies: policies });
    } else {
      const credentialValues = Object.fromEntries(
        descriptor.required_org_credential_fields.map((field) => [
          field.key,
          values[field.key] ?? "",
        ])
      );
      const shared = {
        name: (values[NAME_KEY] ?? "").trim(),
        description: descriptor.description,
        upstream_url_patterns: descriptor.upstream_url_patterns,
        auth_template: descriptor.auth_template,
        action_policies: policies,
      };
      if (existingApp) {
        // Merge creds so non-credential metadata survives a credential edit.
        await updateExternalApp(existingApp.id, {
          ...shared,
          organization_credentials: {
            ...existingApp.organization_credentials,
            ...credentialValues,
          },
        });
      } else {
        await createBuiltInExternalApp({
          ...shared,
          app_type: descriptor.app_type,
          organization_credentials: credentialValues,
        });
      }
    }
    onSaved();
  }

  return (
    <ActionPolicyEditorModal
      onClose={onClose}
      title={
        existingApp ? `Edit ${existingApp.name}` : `Add ${descriptor.name}`
      }
      description={
        managed
          ? "Provided by Onyx — configure what the agent may do."
          : descriptor.setup_instructions
      }
      note={
        managed
          ? "This app is provided by Onyx — credentials are managed for you. Choose what the agent may do below. Users connect this app on the Apps page to make its skill available."
          : undefined
      }
      fields={fields}
      initialFieldValues={initialFieldValues}
      policyItems={descriptor.actions.map((action) => ({
        id: action.action_id,
        name: action.normalised_name,
        description: action.description,
        defaultPolicy: action.default_policy,
      }))}
      initialPolicies={initialPolicies}
      emptyPoliciesMessage="This provider has no actions to configure."
      saveLabel={existingApp ? "Save" : "Add"}
      onSave={save}
    />
  );
}
