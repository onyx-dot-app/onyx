"use client";

import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import {
  BuiltInExternalAppDescriptor,
  ExternalAppAdminResponse,
} from "@/app/craft/v1/apps/registry";
import { upsertExternalApp } from "@/app/craft/services/externalAppsService";

interface ConfigureProviderModalProps {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  descriptor: BuiltInExternalAppDescriptor;
  /** Null → create new instance; non-null → edit existing row. */
  existingApp: ExternalAppAdminResponse | null;
}

export default function ConfigureProviderModal({
  open,
  onClose,
  onSaved,
  descriptor,
  existingApp,
}: ConfigureProviderModalProps) {
  const [name, setName] = useState("");
  const [credentialValues, setCredentialValues] = useState<
    Record<string, string>
  >({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed every time the modal opens so admins can tweak one
  // field without re-entering the rest.
  useEffect(() => {
    if (!open) return;
    setName(existingApp?.name ?? descriptor.name);
    const initial: Record<string, string> = {};
    for (const field of descriptor.required_org_credential_fields) {
      initial[field.key] =
        existingApp?.organization_credentials[field.key] ?? "";
    }
    setCredentialValues(initial);
    setError(null);
  }, [open, descriptor, existingApp]);

  const nameFilled = name.trim().length > 0;
  const credsFilled = descriptor.required_org_credential_fields.every(
    (f) => (credentialValues[f.key] ?? "").trim().length > 0
  );
  const canSave = nameFilled && credsFilled && !isSaving;

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      // Merge so future non-credential metadata on the row (region,
      // instance URL, …) survives a credential edit.
      const merged = {
        ...existingApp?.organization_credentials,
        ...credentialValues,
      };
      await upsertExternalApp({
        id: existingApp?.id ?? null,
        name: name.trim(),
        description: descriptor.description,
        app_type: descriptor.app_type,
        upstream_url_patterns: descriptor.upstream_url_patterns,
        auth_template: descriptor.auth_template,
        organization_credentials: merged,
        // Saving credentials implies enable; disable is a separate
        // action on the admin page.
        enabled: true,
      });
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  }

  const headerTitle = existingApp
    ? `Edit ${existingApp.name}`
    : `Add ${descriptor.name}`;

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          title={headerTitle}
          description={descriptor.setup_instructions}
        />
        <Modal.Body>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
              <Text font="main-ui-action">Name</Text>
              <InputTypeIn
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={descriptor.name}
              />
              <Text font="secondary-body" color="text-03">
                {`A label for this connection. Use a distinct name when adding multiple instances of the same provider (e.g. "${descriptor.name} — Engineering").`}
              </Text>
            </div>

            {descriptor.required_org_credential_fields.map((field) => {
              const Input = field.secret ? PasswordInputTypeIn : InputTypeIn;
              return (
                <div key={field.key} className="flex flex-col gap-1">
                  <Text font="main-ui-action">{field.label}</Text>
                  <Input
                    value={credentialValues[field.key] ?? ""}
                    onChange={(e) =>
                      setCredentialValues((prev) => ({
                        ...prev,
                        [field.key]: e.target.value,
                      }))
                    }
                    placeholder={field.label}
                  />
                  <Text font="secondary-body" color="text-03">
                    {field.description}
                  </Text>
                </div>
              );
            })}
            {error && (
              <Text font="secondary-body" color="text-03">
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
            <Button onClick={save} disabled={!canSave}>
              {isSaving ? "Saving…" : existingApp ? "Save" : "Add"}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
