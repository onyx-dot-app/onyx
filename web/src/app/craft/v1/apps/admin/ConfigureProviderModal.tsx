"use client";

import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import {
  BuiltInProviderPreset,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";

interface ConfigureProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  preset: BuiltInProviderPreset;
  /**
   * The existing row for this provider, if any. When provided the form
   * is pre-filled and the call upserts; when null a new row is created.
   */
  existingApp: ExternalAppAdminResponse | null;
}

export default function ConfigureProviderModal({
  open,
  onClose,
  onSaved,
  preset,
  existingApp,
}: ConfigureProviderModalProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed the form whenever the modal opens or the underlying app changes.
  // We pre-fill from `existingApp.organization_credentials` so admins can
  // tweak one field without re-entering the others.
  useEffect(() => {
    if (!open) return;
    const initial: Record<string, string> = {};
    for (const field of preset.required_org_credential_fields) {
      initial[field.key] =
        existingApp?.organization_credentials[field.key] ?? "";
    }
    setValues(initial);
    setError(null);
  }, [open, preset, existingApp]);

  const allFilled = preset.required_org_credential_fields.every(
    (f) => values[f.key]?.trim().length > 0
  );

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      // Merge new credential values into any other org_credentials the
      // existing row might carry. For built-in providers there are none
      // today, but future providers may store non-credential metadata
      // (region, instance URL, …) and we don't want to clobber it.
      const merged = {
        ...(existingApp?.organization_credentials ?? {}),
        ...values,
      };
      const body = {
        id: existingApp?.id ?? null,
        name: preset.name,
        description: preset.description,
        upstream_urls: preset.upstream_urls,
        auth_template: preset.auth_template,
        organization_credentials: merged,
        enabled: true, // Saving creds implies "enable" — disable is a separate action.
      };
      const res = await fetch("/api/build/admin/apps", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        setError(data.detail ?? `Save failed (HTTP ${res.status}).`);
        return;
      }
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
      <Modal.Content>
        <Modal.Header
          title={`Configure ${preset.name}`}
          description={preset.setup_instructions}
        />
        <Modal.Body>
          <div className="flex flex-col gap-3">
            {preset.required_org_credential_fields.map((field) => {
              const Input = field.secret ? PasswordInputTypeIn : InputTypeIn;
              return (
                <div key={field.key} className="flex flex-col gap-1">
                  <Text mainUiAction>{field.label}</Text>
                  <Input
                    value={values[field.key] ?? ""}
                    onChange={(e) =>
                      setValues((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    placeholder={field.label}
                  />
                  <Text secondaryBody text03>
                    {field.description}
                  </Text>
                </div>
              );
            })}
            {error && (
              <Text secondaryBody className="text-status-error-02">
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
            <Button onClick={save} disabled={!allFilled || isSaving}>
              {isSaving ? "Saving…" : existingApp ? "Save" : "Save & Enable"}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
