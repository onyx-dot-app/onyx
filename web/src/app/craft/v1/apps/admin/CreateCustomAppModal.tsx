"use client";

import { useState } from "react";
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
  const isEdit = existingApp !== null;
  const router = useRouter();

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

  const configDirty = existingApp
    ? name !== existingApp.name ||
      !isEqual(
        new Set(selectedSkillIds),
        new Set(existingApp.associated_skills.map((skill) => skill.id))
      ) ||
      !isEqual(upstreamPatterns, existingApp.upstream_url_patterns) ||
      !isEqual(toRecord(headers), existingApp.auth_template) ||
      !isEqual(toRecord(orgCredentials), existingApp.organization_credentials)
    : Boolean(
        name ||
        upstreamPatterns.length ||
        Object.keys(toRecord(headers)).length ||
        Object.keys(toRecord(orgCredentials)).length
      );
  const unsavedChanges = useUnsavedChangesGuard({ isDirty: configDirty });

  // Headers and org credentials are optional; name + at least one upstream
  // pattern are required.
  const disabledCreateReason = (() => {
    if (isSaving) return "Save is already in progress.";
    if (isEdit && !configDirty) return "Make a change before saving.";
    if (name.trim().length === 0) {
      return "Enter a name before creating this custom app.";
    }
    if (upstreamPatterns.length === 0) {
      return "Add at least one upstream URL pattern. Type a pattern and press Enter.";
    }
    return null;
  })();
  const saveButton = (
    <Button onClick={saveConfig} disabled={disabledCreateReason !== null}>
      {isSaving
        ? isEdit
          ? "Saving…"
          : "Creating…"
        : isEdit
          ? "Save"
          : "Create"}
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
          associated_skill_ids: selectedSkillIds,
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
      upload.dismiss();
    } else {
      unsavedChanges.requestLeave(onClose);
    }
  }

  const confirmationOpen =
    upload.confirmationOpen || unsavedChanges.confirmationOpen;
  const confirmationContent = upload.confirmationOpen ? (
    <UnsavedChangesModalContent
      onCancel={upload.cancelDiscard}
      onDiscard={upload.confirmDiscard}
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
              onClose={upload.close}
              onBusyChange={upload.setBusy}
              onDirtyChange={upload.setDirty}
              preserveDraftOnContinue
              validateDraft={(draft) =>
                existingApp.associated_skills.some(
                  (skill) => skill.name === draft.contents.name
                )
                  ? `App “${existingApp.name}” already has an associated skill named “${draft.contents.name}”. Upload a skill with a different name.`
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
                existingApp ? `Edit ${existingApp.name}` : "Create custom app"
              }
              description={
                isEdit
                  ? "Update gateway settings and manage associated skills."
                  : "Configure how the egress proxy reaches and authenticates this app. A skill is not required."
              }
            />
            <Modal.Body>
              <div className="flex flex-col gap-4">
                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">Name</Text>
                  <InputTypeIn
                    autoFocus={!isEdit}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="My Custom App"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">Upstream URL patterns</Text>
                  <Text font="secondary-body" color="text-03">
                    {
                      "Outbound URLs the proxy may inject credentials into. Use * to match any characters (e.g. https://api.example.com/* covers every path on that host). The host must be literal — no wildcards before the first slash. Type a pattern and press Enter."
                    }
                  </Text>
                  <ListFieldInput
                    values={upstreamPatterns}
                    onChange={setUpstreamPatterns}
                    placeholder="https://api.example.com/*"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">Header credential pattern</Text>
                  <Text font="secondary-body" color="text-03">
                    {`Optional — headers injected into outbound requests. Use {placeholder} for values the user (or org below) supplies, e.g. "Bearer {api_key}". Leave empty to allowlist the upstream patterns without injecting credentials.`}
                  </Text>
                  <InputKeyValue
                    keyTitle="Header"
                    valueTitle="Value"
                    keyPlaceholder="Authorization"
                    valuePlaceholder="Bearer {api_key}"
                    items={headers}
                    onChange={setHeaders}
                    mode="line"
                    addButtonLabel="Add header"
                  />
                </div>

                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action">Organization credentials</Text>
                  <Text font="secondary-body" color="text-03">
                    Optional — values your org pre-fills for every user. Leave
                    empty for apps where each user supplies their own
                    credentials.
                  </Text>
                  <InputKeyValue
                    keyTitle="Credential key"
                    valueTitle="Value"
                    keyPlaceholder="api_key"
                    valuePlaceholder="sk-…"
                    items={orgCredentials}
                    onChange={setOrgCredentials}
                    mode="line"
                    addButtonLabel="Add credential"
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
                    title="Couldn't save"
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
                  Cancel
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
