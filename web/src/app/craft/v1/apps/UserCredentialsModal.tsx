"use client";

import { useEffect, useState } from "react";
import { Modal } from "@opal/components";
import { Button, MessageCard, Text } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import type { IconFunctionComponent } from "@opal/types";

interface UserCredentialsModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after the credentials save so the caller can refresh. */
  onSaved: () => void;
  /** Display name for the modal title. */
  name: string;
  logo: IconFunctionComponent;
  /** Credential fields to collect from the user. */
  credentialKeys: string[];
  /** Previously stored (masked) values, for pre-filling. */
  credentialValues: Record<string, string>;
  save: (values: Record<string, string>) => Promise<void>;
}

/** Turn a credential key (`discord_token`, `apiKey`) into a readable label. */
function humanizeKey(key: string): string {
  return key
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .trim()
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Per-user credential entry for connections without an OAuth flow (custom
 * external apps, API-token MCP servers). Renders one field per credential key,
 * pre-filled with any value the user already stored, and persists via `save`.
 */
export default function UserCredentialsModal({
  open,
  onClose,
  onSaved,
  name,
  logo: Logo,
  credentialKeys,
  credentialValues,
  save,
}: UserCredentialsModalProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed each open so a prior attempt doesn't leak in.
  useEffect(() => {
    if (!open) return;
    const initial: Record<string, string> = {};
    for (const key of credentialKeys) {
      initial[key] = credentialValues[key] ?? "";
    }
    setValues(initial);
    setError(null);
  }, [open, credentialKeys, credentialValues]);

  const canSave =
    credentialKeys.length > 0 &&
    credentialKeys.every((k) => (values[k] ?? "").trim().length > 0) &&
    !isSaving;

  async function saveValues() {
    setIsSaving(true);
    setError(null);
    try {
      await save(values);
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
      <Modal.Content width="md">
        <Modal.Header
          icon={Logo}
          title={`Connect ${name}`}
          description="Enter your credentials to authorize this app for your account."
        />
        <Modal.Body>
          <div className="flex flex-col gap-4 w-full">
            <div className="flex flex-col gap-3 w-full">
              {credentialKeys.map((key) => (
                <div key={key} className="flex flex-col gap-1 w-full">
                  <Text font="main-ui-action">{humanizeKey(key)}</Text>
                  <PasswordInputTypeIn
                    value={values[key] ?? ""}
                    onChange={(e) =>
                      setValues((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    placeholder={key}
                  />
                </div>
              ))}
            </div>

            {error && (
              <MessageCard
                variant="error"
                title="Couldn't connect"
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
            <Button onClick={saveValues} disabled={!canSave}>
              {isSaving ? "Connecting…" : "Connect"}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
