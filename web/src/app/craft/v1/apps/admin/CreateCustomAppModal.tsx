"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { Modal } from "@opal/components";
import {
  Button,
  InputTypeIn,
  MessageCard,
  Text,
  Tooltip,
  Divider,
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
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import {
  skillEditorUrlForApp,
  skillEditUrlForApp,
} from "@/app/craft/v1/apps/admin/skillAssociationNavigation";

interface CreateCustomAppModalProps {
  open: boolean;
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
  open,
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
  const [name, setName] = useState("");
  const [upstreamPatterns, setUpstreamPatterns] = useState<string[]>([]);
  const [headers, setHeaders] = useState<KeyValue[]>([{ key: "", value: "" }]);
  const [orgCredentials, setOrgCredentials] = useState<KeyValue[]>([
    { key: "", value: "" },
  ]);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [uploadOpen, setUploadOpen] = useState(false);
  // Re-seed every time the modal opens: from the existing app when editing,
  // blank when creating. Prevents a prior attempt from leaking in.
  useEffect(() => {
    if (!open) return;
    setActiveApp(existingApp);
    setStep("config");
    setName(existingApp?.name ?? "");
    setUpstreamPatterns(existingApp?.upstream_url_patterns ?? []);
    setHeaders(
      existingApp
        ? toKeyValues(existingApp.auth_template)
        : [{ key: "", value: "" }]
    );
    setOrgCredentials(
      existingApp
        ? toKeyValues(existingApp.organization_credentials)
        : [{ key: "", value: "" }]
    );
    setError(null);
    setSelectedSkillIds(
      existingApp?.associated_skills.map((skill) => skill.id) ?? []
    );
    setUploadOpen(false);
  }, [open, existingApp]);

  // Headers and org credentials are optional; name + at least one upstream
  // pattern are required.
  const disabledCreateReason = (() => {
    if (isSaving) return "Save is already in progress.";
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
        await saveExistingApp();
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

  async function saveExistingApp() {
    if (!existingApp) return null;
    return updateExternalApp(existingApp.id, {
      name: name.trim(),
      upstream_url_patterns: upstreamPatterns,
      auth_template: toRecord(headers),
      organization_credentials: toRecord(orgCredentials),
      associated_skill_ids: selectedSkillIds,
    });
  }

  async function persistActiveApp() {
    if (!activeApp) return false;
    if (existingApp) return saveExistingApp();
    const updated = await updateExternalApp(activeApp.id, {
      associated_skill_ids: selectedSkillIds,
    });
    setActiveApp(updated);
    setSelectedSkillIds(updated.associated_skills.map((skill) => skill.id));
    return updated;
  }

  async function saveSkills(): Promise<boolean> {
    setIsSaving(true);
    setError(null);
    try {
      return (await persistActiveApp()) !== false;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setIsSaving(false);
    }
  }

  async function navigateAfterSave(
    destination: (app: ExternalAppAdminResponse) => Route
  ) {
    setIsSaving(true);
    setError(null);
    try {
      const saved = await persistActiveApp();
      if (!saved) return;
      await onSaved();
      onClose();
      router.push(destination(saved));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  }

  function openSkillEditor(draftId?: string) {
    return navigateAfterSave((app) => skillEditorUrlForApp(app, draftId));
  }

  function openExistingSkill(skillId: string) {
    return navigateAfterSave((app) => skillEditUrlForApp(skillId, app));
  }

  return (
    <>
      <Modal open={open} onOpenChange={(o) => !o && onClose()}>
        <Modal.Content width="lg" height="lg">
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
                        onOpenSkill={(skillId) =>
                          void openExistingSkill(skillId)
                        }
                        onCreateSkill={() => void openSkillEditor()}
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
                  onOpenSkill={(skillId) => void openExistingSkill(skillId)}
                  onCreateSkill={() => void openSkillEditor()}
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
                onClick={onClose}
                disabled={isSaving}
              >
                {step === "skills" ? "Skip for now" : "Cancel"}
              </Button>
              {step === "skills" ? (
                <Button
                  onClick={async () => {
                    if (await saveSkills()) {
                      await onSaved();
                      onClose();
                    }
                  }}
                  disabled={isSaving}
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
        </Modal.Content>
      </Modal>
      {uploadOpen && activeApp && (
        <CreateSkillModal
          open
          skipOverlay
          onClose={() => setUploadOpen(false)}
          onContinue={(draft) => {
            const draftId = stageSkillCreationDraft(draft);
            void openSkillEditor(draftId).finally(() => setUploadOpen(false));
          }}
        />
      )}
    </>
  );
}
