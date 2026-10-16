"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import isEqual from "lodash/isEqual";
import ActionPolicyEditorModal, {
  EditorField,
} from "@/app/craft/v1/apps/admin/ActionPolicyEditorModal";
import {
  BuiltInExternalAppDescriptor,
  ActionPolicy,
  ExternalAppAdminResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import {
  createBuiltInExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";
import AssociatedSkillsEditor from "@/app/craft/v1/apps/admin/AssociatedSkillsEditor";
import ExternalAppSkillsStepModal from "@/app/craft/v1/apps/admin/ExternalAppSkillsStepModal";
import { CreateSkillModalContent } from "@/sections/modals/skills/CreateSkillModal";
import useSkillUploadModal from "@/sections/modals/skills/useSkillUploadModal";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import {
  stageSkillCreationDraft,
  type SkillCreationDraft,
} from "@/lib/skills/creationDraft";
import {
  skillEditorUrlForApp,
  skillEditUrlForApp,
} from "@/app/craft/v1/apps/admin/skillAssociationNavigation";
import { useSyncedAssociatedSkillIds } from "@/lib/externalApps/hooks";
import { externalAppDisplayUrl } from "@/lib/plugins/externalAppDisplayUrl";

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
  const t = useTranslations("craft.apps.configureProvider");
  const tApps = useTranslations("craft.apps");
  const router = useRouter();
  const [usersCanManagePolicies, setUsersCanManagePolicies] = useState(
    existingApp?.users_can_manage_policies ?? true
  );
  const upload = useSkillUploadModal();
  const [createdApp, setCreatedApp] = useState<ExternalAppAdminResponse | null>(
    null
  );
  const [selectedSkillIds, setSelectedSkillIds] =
    useSyncedAssociatedSkillIds(existingApp);
  const existingAssociationDirty =
    existingApp !== null &&
    !isEqual(
      new Set(selectedSkillIds),
      new Set(existingApp.associated_skills.map((skill) => skill.id))
    );
  const associationPatch = existingAssociationDirty
    ? { associated_skill_ids: selectedSkillIds }
    : {};
  // Managed built-ins (cloud): Onyx owns creds/config, so the modal only edits
  // policies — cred fields are hidden and the backend ignores them anyway.
  const managed = existingApp?.is_onyx_managed ?? false;

  const fields: EditorField[] = managed
    ? []
    : [
        {
          key: NAME_KEY,
          label: t("fields.name.label"),
          description: t("fields.name.description", { name: descriptor.name }),
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
  const storedPolicies: Record<string, ActionPolicy> = {};
  for (const action of existingApp?.actions ?? []) {
    storedPolicies[action.action_id] = action.state;
  }
  const initialPolicies = Object.fromEntries(
    descriptor.actions.map((action): [string, ActionPolicy] => [
      action.action_id,
      storedPolicies[action.action_id] ?? action.default_policy,
    ])
  );

  async function save(
    values: Record<string, string>,
    policies: Record<string, ActionPolicy>
  ) {
    if (managed && existingApp) {
      // Managed: only policies are persisted; a partial PATCH leaves the rest.
      await updateExternalApp(existingApp.id, {
        action_policies: policies,
        users_can_manage_policies: usersCanManagePolicies,
        ...associationPatch,
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
        users_can_manage_policies: usersCanManagePolicies,
      };
      if (existingApp) {
        // Merge creds so non-credential metadata survives a credential edit.
        await updateExternalApp(existingApp.id, {
          ...shared,
          organization_credentials: {
            ...existingApp.organization_credentials,
            ...credentialValues,
          },
          ...associationPatch,
        });
      } else {
        const created = await createBuiltInExternalApp({
          ...shared,
          app_type: descriptor.app_type,
          organization_credentials: credentialValues,
        });
        setCreatedApp(created);
      }
    }
    onSaved();
  }

  function navigateToSkillEditor(draftId?: string) {
    if (!existingApp) return;
    router.push(skillEditorUrlForApp(existingApp, draftId));
  }

  function navigateToExistingSkill(skillId: string) {
    if (!existingApp) return;
    router.push(skillEditUrlForApp(skillId, existingApp));
  }

  function validateUploadedSkill(draft: SkillCreationDraft): string | null {
    return existingApp?.associated_skills.some(
      (skill) => skill.name === draft.contents.name
    )
      ? tApps("errors.duplicateSkillName", {
          appName: existingApp.name,
          skillName: draft.contents.name,
        })
      : null;
  }

  if (createdApp) {
    return (
      <ExternalAppSkillsStepModal
        app={createdApp}
        onClose={onClose}
        onSaved={onSaved}
      />
    );
  }

  return (
    <ActionPolicyEditorModal
      alternateContent={
        upload.isOpen && existingApp
          ? ({ requestLeave, hidden }) => (
              <>
                <CreateSkillModalContent
                  hidden={hidden || upload.confirmationOpen}
                  onRequestClose={upload.requestDismiss}
                  onBusyChange={upload.setBusy}
                  onDirtyChange={upload.setDirty}
                  preserveDraftOnContinue
                  validateDraft={validateUploadedSkill}
                  onContinue={(draft) => {
                    requestLeave(() =>
                      navigateToSkillEditor(stageSkillCreationDraft(draft))
                    );
                  }}
                />
                {upload.confirmationOpen && (
                  <UnsavedChangesModalContent
                    onCancel={upload.cancelDiscard}
                    onDiscard={upload.discardAndClose}
                  />
                )}
              </>
            )
          : undefined
      }
      alternateContentConfirmationOpen={upload.confirmationOpen}
      usersCanManagePolicies={usersCanManagePolicies}
      onUsersCanManagePoliciesChange={setUsersCanManagePolicies}
      isAdditionalContentDirty={
        existingAssociationDirty ||
        usersCanManagePolicies !==
          (existingApp?.users_can_manage_policies ?? true)
      }
      onClose={upload.isOpen ? upload.requestDismiss : onClose}
      title={existingApp?.name ?? descriptor.name}
      displayUrl={externalAppDisplayUrl(
        existingApp?.upstream_url_patterns ?? descriptor.upstream_url_patterns
      )}
      icon={getAppTypeLogo(descriptor.app_type)}
      authenticationInstructions={
        managed ? undefined : descriptor.setup_instructions
      }
      note={managed ? t("managedNote") : undefined}
      fields={fields}
      initialFieldValues={initialFieldValues}
      policyItems={descriptor.actions.map((action) => ({
        id: action.action_id,
        name: action.normalised_name,
        description: action.description,
        fallbackPolicy: action.default_policy,
      }))}
      initialPolicies={initialPolicies}
      emptyPoliciesMessage={t("emptyPolicies")}
      saveLabel={existingApp ? t("saveButton") : t("addButton")}
      autoFocusFirstField={existingApp === null}
      allowPristineSave={existingApp === null}
      onSave={save}
      closeAfterSave={existingApp !== null}
      discardOnClose={existingApp === null}
      skillsContent={
        existingApp
          ? (requestLeave) => (
              <AssociatedSkillsEditor
                app={existingApp}
                selectedSkillIds={selectedSkillIds}
                onChange={setSelectedSkillIds}
                onOpenSkill={(skillId) =>
                  requestLeave(() => navigateToExistingSkill(skillId))
                }
                onCreateSkill={() =>
                  requestLeave(() => navigateToSkillEditor())
                }
                onUploadSkill={upload.open}
              />
            )
          : undefined
      }
    />
  );
}
