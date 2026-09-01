"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import { useRouter } from "next/navigation";
import isEqual from "lodash/isEqual";
import {
  Button,
  Divider,
  InputTypeIn,
  MessageCard,
  Modal,
  Text,
  Tooltip,
} from "@opal/components";
import { ListFieldInput } from "@/refresh-components/inputs/ListFieldInput";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import {
  createCustomExternalApp,
  updateExternalApp,
} from "@/app/craft/services/externalAppsService";
import AssociatedSkillsEditor from "@/app/craft/v1/apps/admin/AssociatedSkillsEditor";
import ExternalAppSkillsStepModal from "@/app/craft/v1/apps/admin/ExternalAppSkillsStepModal";
import { CreateSkillModalContent } from "@/sections/modals/skills/CreateSkillModal";
import useSkillUploadModal from "@/sections/modals/skills/useSkillUploadModal";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import {
  stageSkillCreationDraft,
  type SkillCreationDraft,
} from "@/lib/skills/creationDraft";
import {
  skillEditorUrlForApp,
  skillEditUrlForApp,
} from "@/app/craft/v1/apps/admin/skillAssociationNavigation";
import { useSyncedAssociatedSkillIds } from "@/lib/externalApps/hooks";

interface CreateCustomAppModalProps {
  onClose: () => void;
  /** Invoked after a successful create/edit so callers can refresh their list. */
  onSaved: () => void;
  /** Null → create a new custom app; non-null → edit that app's config. */
  existingApp: ExternalAppAdminResponse | null;
}

/** Collapse a key-value list into a record, dropping rows with an empty key. */
function toRecord(items: KeyValue[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const { key, value } of items) {
    const trimmedKey = key.trim();
    if (trimmedKey) out[trimmedKey] = value;
  }
  return out;
}

/** Expand a record into editable rows, seeding one empty row when empty. */
function toKeyValues(record: Record<string, string>): KeyValue[] {
  const entries = Object.entries(record).map(([key, value]) => ({
    key,
    value,
  }));
  return entries.length > 0 ? entries : [{ key: "", value: "" }];
}

export default function CreateCustomAppModal({
  onClose,
  onSaved,
  existingApp,
}: CreateCustomAppModalProps) {
  const t = useTranslations("craft.apps.customApp");
  const tApps = useTranslations("craft.apps");
  const isEdit = existingApp !== null;
  const router = useRouter();
  // Focus the name field for new apps only; edits keep the natural tab order.
  const focusNameOnMount = useFocusOnMount<HTMLInputElement>(!isEdit);

  const [createdApp, setCreatedApp] = useState<ExternalAppAdminResponse | null>(
    null
  );
  const [name, setName] = useState(existingApp?.name ?? "");
  const [upstreamPatterns, setUpstreamPatterns] = useState<string[]>(
    existingApp?.upstream_url_patterns ?? []
  );
  const [headers, setHeaders] = useState<KeyValue[]>(
    existingApp
      ? toKeyValues(existingApp.auth_template)
      : [{ key: "", value: "" }]
  );
  const [orgCredentials, setOrgCredentials] = useState<KeyValue[]>(
    existingApp
      ? toKeyValues(existingApp.organization_credentials)
      : [{ key: "", value: "" }]
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkillIds, setSelectedSkillIds] =
    useSyncedAssociatedSkillIds(existingApp);
  const upload = useSkillUploadModal();

  const associationDirty =
    existingApp !== null &&
    !isEqual(
      new Set(selectedSkillIds),
      new Set(existingApp.associated_skills.map((skill) => skill.id))
    );
  const configDirty = existingApp
    ? name !== existingApp.name ||
      associationDirty ||
      !isEqual(upstreamPatterns, existingApp.upstream_url_patterns) ||
      !isEqual(toRecord(headers), existingApp.auth_template) ||
      !isEqual(toRecord(orgCredentials), existingApp.organization_credentials)
    : Boolean(
        name ||
        upstreamPatterns.length ||
        Object.keys(toRecord(headers)).length ||
        Object.keys(toRecord(orgCredentials)).length
      );
  const unsavedChanges = useUnsavedChangesGuard({
    isDirty: createdApp === null && configDirty,
  });

  // Headers and org credentials are optional; name + at least one upstream
  // pattern are required.
  const disabledCreateReason = (() => {
    if (isSaving) return t("disabled.saving");
    if (isEdit && !configDirty) return t("disabled.pristine");
    if (name.trim().length === 0) {
      return t("disabled.nameMissing");
    }
    if (upstreamPatterns.length === 0) {
      return t("disabled.patternMissing");
    }
    return null;
  })();
  const saveButton = (
    <Button onClick={saveConfig} disabled={disabledCreateReason !== null}>
      {isSaving
        ? isEdit
          ? t("savingButton")
          : t("creatingButton")
        : isEdit
          ? t("saveButton")
          : t("createButton")}
    </Button>
  );

  async function saveConfig() {
    setIsSaving(true);
    setError(null);
    try {
      if (existingApp) {
        await updateExternalApp(existingApp.id, {
          name: name.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
          ...(associationDirty
            ? { associated_skill_ids: selectedSkillIds }
            : {}),
        });
        onSaved();
        onClose();
      } else {
        const created = await createCustomExternalApp({
          name: name.trim(),
          upstream_url_patterns: upstreamPatterns,
          auth_template: toRecord(headers),
          organization_credentials: toRecord(orgCredentials),
        });
        setCreatedApp(created);
        onSaved();
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      setError(detail);
    } finally {
      setIsSaving(false);
    }
  }

  function openSkillEditor(draft?: SkillCreationDraft) {
    if (!existingApp) return;
    unsavedChanges.requestLeave(() =>
      router.push(
        skillEditorUrlForApp(
          existingApp,
          draft ? stageSkillCreationDraft(draft) : undefined
        )
      )
    );
  }

  function openExistingSkill(skillId: string) {
    if (!existingApp) return;
    unsavedChanges.requestLeave(() =>
      router.push(skillEditUrlForApp(skillId, existingApp))
    );
  }

  function handleDismiss(event: Event) {
    const preventedByModal = event.defaultPrevented;
    event.preventDefault();
    if (preventedByModal || isSaving) return;
    if (unsavedChanges.confirmationOpen) {
      unsavedChanges.cancelLeave();
      return;
    }
    if (upload.isOpen) {
      upload.requestDismiss();
    } else {
      unsavedChanges.requestLeave(onClose);
    }
  }

  const confirmationOpen =
    upload.confirmationOpen || unsavedChanges.confirmationOpen;
  const confirmationContent = upload.confirmationOpen ? (
    <UnsavedChangesModalContent
      onCancel={upload.cancelDiscard}
      onDiscard={upload.discardAndClose}
    />
  ) : unsavedChanges.confirmationOpen ? (
    <UnsavedChangesModalContent
      onCancel={unsavedChanges.cancelLeave}
      onDiscard={unsavedChanges.discardAndLeave}
    />
  ) : null;

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
    <Modal open>
      <Modal.Content
        width={confirmationOpen || upload.isOpen ? "sm" : "lg"}
        height={confirmationOpen || upload.isOpen ? "fit" : "lg"}
        onOpenAutoFocus={(event) => {
          if (isEdit) event.preventDefault();
        }}
        preventAccidentalClose={!confirmationOpen}
        onInteractOutside={handleDismiss}
        onEscapeKeyDown={handleDismiss}
      >
        {upload.isOpen && existingApp ? (
          <>
            <CreateSkillModalContent
              hidden={confirmationOpen}
              onRequestClose={upload.requestDismiss}
              onBusyChange={upload.setBusy}
              onDirtyChange={upload.setDirty}
              preserveDraftOnContinue
              validateDraft={(draft) =>
                existingApp.associated_skills.some(
                  (skill) => skill.name === draft.contents.name
                )
                  ? tApps("errors.duplicateSkillName", {
                      appName: existingApp.name,
                      skillName: draft.contents.name,
                    })
                  : null
              }
              onContinue={openSkillEditor}
            />
            {confirmationContent}
          </>
        ) : confirmationContent ? (
          confirmationContent
        ) : (
          <>
            <Modal.Header
              title={
                existingApp
                  ? t("editTitle", { name: existingApp.name })
                  : t("createTitle")
              }
              description={
                isEdit ? t("editDescription") : t("createDescription")
              }
            />
            <Modal.Body>
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">{t("fields.name.label")}</Text>
                  <InputTypeIn
                    ref={focusNameOnMount}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder={t("fields.name.placeholder")}
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">
                    {t("fields.upstreamPatterns.label")}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {t("fields.upstreamPatterns.description")}
                  </Text>
                  <ListFieldInput
                    values={upstreamPatterns}
                    onChange={setUpstreamPatterns}
                    placeholder="https://api.example.com/*"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">{t("fields.headers.label")}</Text>
                  <Text font="secondary-body" color="text-03">
                    {t("fields.headers.description")}
                  </Text>
                  <InputKeyValue
                    keyTitle={t("fields.headers.keyTitle")}
                    valueTitle={t("fields.headers.valueTitle")}
                    keyPlaceholder="Authorization"
                    valuePlaceholder="Bearer {api_key}"
                    items={headers}
                    onChange={setHeaders}
                    mode="line"
                    addButtonLabel={t("fields.headers.addButton")}
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">
                    {t("fields.orgCredentials.label")}
                  </Text>
                  <Text font="secondary-body" color="text-03">
                    {t("fields.orgCredentials.description")}
                  </Text>
                  <InputKeyValue
                    keyTitle={t("fields.orgCredentials.keyTitle")}
                    valueTitle={t("fields.orgCredentials.valueTitle")}
                    keyPlaceholder="api_key"
                    valuePlaceholder="sk-…"
                    items={orgCredentials}
                    onChange={setOrgCredentials}
                    mode="line"
                    addButtonLabel={t("fields.orgCredentials.addButton")}
                  />
                </div>

                {existingApp && (
                  <>
                    <Divider />
                    <AssociatedSkillsEditor
                      app={existingApp}
                      selectedSkillIds={selectedSkillIds}
                      onChange={setSelectedSkillIds}
                      onOpenSkill={openExistingSkill}
                      onCreateSkill={openSkillEditor}
                      onUploadSkill={upload.open}
                    />
                  </>
                )}

                {error && (
                  <MessageCard
                    variant="error"
                    title={t("errors.saveFailedTitle")}
                    description={error}
                  />
                )}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <div className="flex justify-end gap-2 w-full">
                <Button
                  prominence="secondary"
                  onClick={() => unsavedChanges.requestLeave(onClose)}
                  disabled={isSaving}
                >
                  {t("cancelButton")}
                </Button>
                {disabledCreateReason ? (
                  <Tooltip tooltip={disabledCreateReason}>
                    <span className="inline-flex">{saveButton}</span>
                  </Tooltip>
                ) : (
                  saveButton
                )}
              </div>
            </Modal.Footer>
          </>
        )}
      </Modal.Content>
    </Modal>
  );
}
