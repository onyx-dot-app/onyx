"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import isEqual from "lodash/isEqual";
import { Divider } from "@opal/components";
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
  type UpdateExternalAppBody,
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

// Field key for the instance name; prefixed so it can never collide with a
// descriptor-declared credential key.
const NAME_KEY = "__name";

interface ConfigureProviderModalProps {
  mode?: "configuration" | "permissions";
  onClose: () => void;
  onSaved: () => Promise<void> | void;
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
  mode,
}: ConfigureProviderModalProps) {
  const showPolicies = mode !== "configuration";
  const showConfiguration = mode !== "permissions";
  const t = useTranslations("craft.apps.configureProvider");
  const tApps = useTranslations("craft.apps");
  const router = useRouter();
  const upload = useSkillUploadModal();
  const [createdApp, setCreatedApp] = useState<ExternalAppAdminResponse | null>(
    null
  );
  const [selectedSkillIds, setSelectedSkillIds] =
    useSyncedAssociatedSkillIds(existingApp);
  const existingAssociationDirty =
    showConfiguration &&
    existingApp !== null &&
    !isEqual(
      new Set(selectedSkillIds),
      new Set(existingApp.associated_skills.map((skill) => skill.id))
    );
  // Onyx owns managed credentials; admins can edit policies and skill associations.
  const managed = existingApp?.is_onyx_managed ?? false;

  const fields: EditorField[] =
    managed || !showConfiguration
      ? []
      : [
          {
            key: NAME_KEY,
            label: t("fields.name.label"),
            description: t("fields.name.description", {
              name: descriptor.name,
            }),
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
  const [initialPolicies] = useState(() =>
    showPolicies
      ? Object.fromEntries(
          descriptor.actions.map((action): [string, EndpointPolicy] => [
            action.action_id,
            storedPolicies[action.action_id] ?? action.default_policy,
          ])
        )
      : {}
  );

  async function save(
    values: Record<string, string>,
    policies: Record<string, EndpointPolicy>
  ) {
    const credentialValues = Object.fromEntries(
      descriptor.required_org_credential_fields.map((field) => [
        field.key,
        values[field.key] ?? "",
      ])
    );
    const configuration = {
      name: (values[NAME_KEY] ?? "").trim(),
      upstream_url_patterns: descriptor.upstream_url_patterns,
      auth_template: descriptor.auth_template,
    };
    if (existingApp) {
      const update: UpdateExternalAppBody = {};
      if (showPolicies) {
        update.action_policies = Object.fromEntries(
          Object.entries(policies).filter(
            ([id, value]) => initialPolicies[id] !== value
          )
        );
      }
      if (showConfiguration && !managed) {
        Object.assign(update, configuration, {
          organization_credentials: {
            ...existingApp.organization_credentials,
            ...credentialValues,
          },
        });
      }
      if (existingAssociationDirty)
        update.associated_skill_ids = selectedSkillIds;
      await updateExternalApp(existingApp.id, update);
    } else {
      const created = await createBuiltInExternalApp({
        ...configuration,
        action_policies: policies,
        app_type: descriptor.app_type,
        organization_credentials: credentialValues,
      });
      setCreatedApp(created);
    }
    await onSaved();
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
      isAdditionalContentDirty={existingAssociationDirty}
      onClose={upload.isOpen ? upload.requestDismiss : onClose}
      title={
        existingApp
          ? t("editTitle", { name: existingApp.name })
          : t("addTitle", { name: descriptor.name })
      }
      description={
        mode === "permissions"
          ? t("permissionsDescription")
          : managed
            ? mode === "configuration"
              ? t("managedConfigurationDescription")
              : t("managedDescription")
            : descriptor.setup_instructions
      }
      note={managed && mode !== "configuration" ? t("managedNote") : undefined}
      fields={fields}
      initialFieldValues={showConfiguration ? initialFieldValues : {}}
      showPolicies={showPolicies}
      policyItems={descriptor.actions.map((action) => ({
        id: action.action_id,
        name: action.normalised_name,
        description: action.description,
        defaultPolicy: action.default_policy,
      }))}
      initialPolicies={initialPolicies}
      emptyPoliciesMessage={t("emptyPolicies")}
      saveLabel={existingApp ? t("saveButton") : t("addButton")}
      autoFocusFirstField={existingApp === null}
      allowPristineSave={existingApp === null}
      onSave={save}
      closeAfterSave={existingApp !== null}
      bodyAfterPolicies={
        existingApp && showConfiguration
          ? (requestLeave) => (
              <>
                <Divider />
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
              </>
            )
          : undefined
      }
    />
  );
}
