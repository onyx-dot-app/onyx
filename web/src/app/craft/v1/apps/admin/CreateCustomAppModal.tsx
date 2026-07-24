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
import { CreateSkillModalContent } from "@/sections/modals/skills/CreateSkillModal";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import {
  skillEditorUrlForApp,
  skillEditUrlForApp,
} from "@/app/craft/v1/apps/admin/skillAssociationNavigation";

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

  const [activeApp, setActiveApp] = useState<ExternalAppAdminResponse | null>(
    existingApp
  );
  const [step, setStep] = useState<"config" | "skills">("config");
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
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>(
    existingApp?.associated_skills.map((skill) => skill.id) ?? []
  );
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);

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
  const skillsDirty =
    activeApp !== null &&
    !isEqual(
      new Set(selectedSkillIds),
      new Set(activeApp.associated_skills.map((skill) => skill.id))
    );
  const unsavedChanges = useUnsavedChangesGuard({
    isDirty: step === "config" ? configDirty : skillsDirty,
  });

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
        setActiveApp(created);
        setSelectedSkillIds([]);
        setStep("skills");
        onSaved();
      }
    } catch (e) {
      const detail = e instanceof Error ? e.message : String(e);
      setError(detail);
    } finally {
      setIsSaving(false);
    }
  }

  async function saveSkills(): Promise<boolean> {
    if (!activeApp) return false;
    setIsSaving(true);
    setError(null);
    try {
      const updated = await updateExternalApp(activeApp.id, {
        associated_skill_ids: selectedSkillIds,
      });
      setActiveApp(updated);
      setSelectedSkillIds(updated.associated_skills.map((skill) => skill.id));
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  function openSkillEditor(draftId?: string) {
    if (!activeApp) return;
    unsavedChanges.requestLeave(() =>
      router.push(skillEditorUrlForApp(activeApp, draftId))
    );
  }

  function openExistingSkill(skillId: string) {
    if (!activeApp) return;
    unsavedChanges.requestLeave(() =>
      router.push(skillEditUrlForApp(skillId, activeApp))
    );
  }

  return (
    <>
      <Modal
        open
        onOpenChange={(o) => {
          if (o) return;
          if (uploadOpen) {
            if (!uploadBusy) setUploadOpen(false);
          } else {
            unsavedChanges.requestLeave(onClose);
          }
        }}
      >
        <Modal.Content
          width={uploadOpen ? "sm" : "lg"}
          height={uploadOpen ? "fit" : "lg"}
        >
          {uploadOpen && activeApp ? (
            <CreateSkillModalContent
              onClose={() => setUploadOpen(false)}
              onBusyChange={setUploadBusy}
              onContinue={(draft) => {
                const draftId = stageSkillCreationDraft(draft);
                setUploadOpen(false);
                openSkillEditor(draftId);
              }}
            />
          ) : (
            <>
              <Modal.Header
                title={
                  step === "skills" && activeApp
                    ? `Add skills to ${activeApp.name}`
                    : existingApp
                      ? `Edit ${existingApp.name}`
                      : "Create custom app"
                }
                description={
                  step === "skills"
                    ? "Optional — associate existing skills or create one for this app."
                    : isEdit
                      ? "Update gateway settings and manage associated skills."
                      : "Configure how the egress proxy reaches and authenticates this app. A skill is not required."
                }
              />
              <Modal.Body>
                <div className="flex flex-col gap-4">
                  {step === "config" && (
                    <>
                      <div className="flex flex-col gap-1">
                        <Text font="main-ui-action">Name</Text>
                        <InputTypeIn
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
                        <Text font="main-ui-action">
                          Header credential pattern
                        </Text>
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
                        <Text font="main-ui-action">
                          Organization credentials
                        </Text>
                        <Text font="secondary-body" color="text-03">
                          Optional — values your org pre-fills for every user.
                          Leave empty for apps where each user supplies their
                          own credentials.
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
                            onUploadSkill={() => setUploadOpen(true)}
                          />
                        </>
                      )}
                    </>
                  )}

                  {step === "skills" && activeApp && (
                    <AssociatedSkillsEditor
                      app={activeApp}
                      selectedSkillIds={selectedSkillIds}
                      onChange={setSelectedSkillIds}
                      onOpenSkill={openExistingSkill}
                      onCreateSkill={openSkillEditor}
                      onUploadSkill={() => setUploadOpen(true)}
                    />
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
                    {step === "skills" ? "Skip for now" : "Cancel"}
                  </Button>
                  {step === "skills" ? (
                    <Button
                      onClick={async () => {
                        if (await saveSkills()) {
                          onSaved();
                          onClose();
                        }
                      }}
                      disabled={isSaving || !skillsDirty}
                    >
                      {isSaving ? "Saving…" : "Save skills"}
                    </Button>
                  ) : disabledCreateReason ? (
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
      <UnsavedChangesModal
        open={unsavedChanges.confirmationOpen}
        onCancel={unsavedChanges.cancelLeave}
        onDiscard={unsavedChanges.discardAndLeave}
      />
    </>
  );
}
