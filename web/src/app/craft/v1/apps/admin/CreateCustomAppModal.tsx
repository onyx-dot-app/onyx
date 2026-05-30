"use client";

import { useEffect, useRef, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Button, InputTypeIn, MessageCard, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { ListFieldInput } from "@/refresh-components/inputs/ListFieldInput";
import InputKeyValue, {
  KeyValue,
} from "@/refresh-components/inputs/InputKeyValue";
import { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import { upsertCustomExternalApp } from "@/app/craft/services/externalAppsService";

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

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [upstreamPatterns, setUpstreamPatterns] = useState<string[]>([]);
  const [headers, setHeaders] = useState<KeyValue[]>([{ key: "", value: "" }]);
  const [orgCredentials, setOrgCredentials] = useState<KeyValue[]>([
    { key: "", value: "" },
  ]);
  const [file, setFile] = useState<File | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Re-seed every time the modal opens: from the existing app when editing,
  // blank when creating. Prevents a prior attempt from leaking in.
  useEffect(() => {
    if (!open) return;
    setName(existingApp?.name ?? "");
    setDescription(existingApp?.description ?? "");
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
    setFile(null);
    setError(null);
  }, [open, existingApp]);

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    setFile(event.target.files?.[0] ?? null);
  }

  // Headers and organization credentials are both optional: an app may inject
  // no credentials at all and simply allowlist its upstream patterns. Name and
  // at least one upstream pattern are always required; a bundle is required
  // only when creating (the bundle can't be replaced through this edit path).
  const canSave =
    name.trim().length > 0 &&
    upstreamPatterns.length > 0 &&
    (isEdit || file !== null) &&
    !isSaving;

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      // Custom apps always go through the custom endpoint. On edit a bundle is
      // optional (replaces the existing one when present); enabled is toggled
      // separately on the card, so preserve the existing value here.
      await upsertCustomExternalApp({
        id: existingApp?.id,
        name: name.trim(),
        description: description.trim(),
        upstream_url_patterns: upstreamPatterns,
        auth_template: toRecord(headers),
        organization_credentials: toRecord(orgCredentials),
        enabled: existingApp?.enabled ?? true,
        bundle: file ?? undefined,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={existingApp ? `Edit ${existingApp.name}` : "Create custom app"}
          description={
            isEdit
              ? "Update this custom app's configuration, and optionally upload a new bundle to replace its files."
              : "Define a custom external app: upload its skill bundle and configure how the egress proxy authenticates outbound requests."
          }
        />
        <Modal.Body>
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Name</Text>
              <InputTypeIn
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="My Custom App"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Description</Text>
              <InputTypeIn
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional — defaults to the bundle's SKILL.md description"
              />
            </div>

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Upstream URL patterns</Text>
              <Text font="secondary-body" color="text-03">
                Outbound URLs the proxy may inject credentials into. Type a
                pattern and press Enter.
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
                Optional — values your org pre-fills for every user. Leave empty
                for apps where each user supplies their own credentials.
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

            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">
                {isEdit ? "Replace bundle (.zip)" : "Bundle (.zip)"}
              </Text>
              <Text font="secondary-body" color="text-03">
                {isEdit
                  ? "Optional — upload a new zip to replace the current bundle. Leave empty to keep it. The slug stays the same."
                  : "A zip containing SKILL.md plus any other files. The filename becomes the app slug."}
              </Text>
              <div className="flex items-center gap-2">
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".zip,application/zip"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <Button
                  icon={SvgUploadCloud}
                  prominence="secondary"
                  onClick={() => fileInputRef.current?.click()}
                >
                  {file
                    ? "Change file"
                    : isEdit
                      ? "Choose new zip"
                      : "Choose zip"}
                </Button>
                <Text font="main-ui-body" color="text-03">
                  {file
                    ? file.name
                    : isEdit
                      ? "Keeping current bundle"
                      : "No file selected"}
                </Text>
              </div>
            </div>

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
              Cancel
            </Button>
            <Button onClick={save} disabled={!canSave}>
              {isSaving
                ? isEdit
                  ? "Saving…"
                  : "Creating…"
                : isEdit
                  ? "Save"
                  : "Create"}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
