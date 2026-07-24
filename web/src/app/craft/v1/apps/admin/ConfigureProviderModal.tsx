"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button, Divider, MessageCard, Modal } from "@opal/components";
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
import AssociatedSkillsEditor from "@/app/craft/v1/apps/admin/AssociatedSkillsEditor";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import {
  skillEditorUrlForApp,
  skillEditUrlForApp,
} from "@/app/craft/v1/apps/admin/skillAssociationNavigation";

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
  const router = useRouter();
  const [selectedSkillIds, setSelectedSkillIds] = useState(
    existingApp?.associated_skills.map((skill) => skill.id) ?? []
  );
  const [uploadOpen, setUploadOpen] = useState(false);
  const [createdApp, setCreatedApp] = useState<ExternalAppAdminResponse | null>(
    null
  );
  const [isSavingSkills, setIsSavingSkills] = useState(false);
  const [skillsError, setSkillsError] = useState<string | null>(null);
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
      await updateExternalApp(existingApp.id, {
        action_policies: policies,
        associated_skill_ids: selectedSkillIds,
      });
    } else {
      const credentialValues = Object.fromEntries(
        descriptor.required_org_credential_fields.map((field) => [
          field.key,
          values[field.key] ?? "",
        ])
      );
      const shared = {
        name: (values[NAME_KEY] ?? "").trim(),
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
          associated_skill_ids: selectedSkillIds,
        });
      } else {
        const created = await createBuiltInExternalApp({
          ...shared,
          app_type: descriptor.app_type,
          organization_credentials: credentialValues,
        });
        setCreatedApp(created);
        setSelectedSkillIds([]);
      }
    }
    onSaved();
  }

  function navigateToSkillEditor(draftId?: string) {
    const app = existingApp ?? createdApp;
    if (!app) return;
    onClose();
    router.push(skillEditorUrlForApp(app, draftId));
  }

  function navigateToExistingSkill(skillId: string) {
    const app = existingApp ?? createdApp;
    if (!app) return;
    onClose();
    router.push(skillEditUrlForApp(skillId, app));
  }

  async function saveCreatedAppSkills(): Promise<boolean> {
    if (!createdApp) return false;
    setIsSavingSkills(true);
    setSkillsError(null);
    try {
      const updated = await updateExternalApp(createdApp.id, {
        associated_skill_ids: selectedSkillIds,
      });
      setCreatedApp(updated);
      await onSaved();
      return true;
    } catch (error) {
      setSkillsError(error instanceof Error ? error.message : String(error));
      return false;
    } finally {
      setIsSavingSkills(false);
    }
  }

  if (createdApp) {
    return (
      <>
        <Modal open onOpenChange={(open) => !open && onClose()}>
          <Modal.Content width="lg" height="lg">
            <Modal.Header
              title={`Add skills to ${createdApp.name}`}
              description="Optional — associate existing skills or create one for this app."
            />
            <Modal.Body>
              <div className="flex flex-col gap-3">
                <AssociatedSkillsEditor
                  app={createdApp}
                  selectedSkillIds={selectedSkillIds}
                  onChange={setSelectedSkillIds}
                  onOpenSkill={async (skillId) => {
                    if (await saveCreatedAppSkills()) {
                      navigateToExistingSkill(skillId);
                    }
                  }}
                  onCreateSkill={async () => {
                    if (await saveCreatedAppSkills()) navigateToSkillEditor();
                  }}
                  onUploadSkill={async () => {
                    if (await saveCreatedAppSkills()) setUploadOpen(true);
                  }}
                />
                {skillsError && (
                  <MessageCard
                    variant="error"
                    title="Couldn't save"
                    description={skillsError}
                  />
                )}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <div className="flex w-full justify-end gap-2">
                <Button
                  prominence="secondary"
                  onClick={onClose}
                  disabled={isSavingSkills}
                >
                  Skip for now
                </Button>
                <Button
                  disabled={isSavingSkills}
                  onClick={async () => {
                    if (await saveCreatedAppSkills()) onClose();
                  }}
                >
                  {isSavingSkills ? "Saving…" : "Save skills"}
                </Button>
              </div>
            </Modal.Footer>
          </Modal.Content>
        </Modal>
        {uploadOpen && (
          <CreateSkillModal
            open
            skipOverlay
            onClose={() => setUploadOpen(false)}
            onContinue={(draft) => {
              navigateToSkillEditor(stageSkillCreationDraft(draft));
            }}
          />
        )}
      </>
    );
  }

  return (
    <>
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
            ? "This app is provided by Onyx — credentials are managed for you. Choose what the agent may do below. Users connect it from the Apps page."
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
        closeAfterSave={existingApp !== null}
        bodyAfterPolicies={
          existingApp
            ? (saveWithoutClosing) => (
                <>
                  <Divider />
                  <AssociatedSkillsEditor
                    app={existingApp}
                    selectedSkillIds={selectedSkillIds}
                    onChange={setSelectedSkillIds}
                    onOpenSkill={async (skillId) => {
                      if (await saveWithoutClosing()) {
                        navigateToExistingSkill(skillId);
                      }
                    }}
                    onCreateSkill={async () => {
                      if (await saveWithoutClosing()) navigateToSkillEditor();
                    }}
                    onUploadSkill={async () => {
                      if (await saveWithoutClosing()) setUploadOpen(true);
                    }}
                  />
                </>
              )
            : undefined
        }
      />
      {uploadOpen && existingApp && (
        <CreateSkillModal
          open
          skipOverlay
          onClose={() => setUploadOpen(false)}
          onContinue={(draft) => {
            navigateToSkillEditor(stageSkillCreationDraft(draft));
          }}
        />
      )}
    </>
  );
}
