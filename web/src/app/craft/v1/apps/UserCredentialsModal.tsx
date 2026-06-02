"use client";

import { useEffect, useState } from "react";
import Modal from "@/refresh-components/Modal";
import { Button, MessageCard, Text } from "@opal/components";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import {
  ExternalAppUserResponse,
  getAppTypeLogo,
} from "@/app/craft/v1/apps/registry";
import { upsertUserCredentials } from "@/app/craft/services/externalAppsService";

interface UserCredentialsModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after the credentials save so the caller can refresh. */
  onSaved: () => void;
  userApp: ExternalAppUserResponse;
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
 * Per-user credential entry for apps without an OAuth flow (custom apps).
 * Renders one field per `credential_keys` the app still needs from the user,
 * pre-filled with any value they've already stored, and persists them.
 */
export default function UserCredentialsModal({
  open,
  onClose,
  onSaved,
  userApp,
}: UserCredentialsModalProps) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Re-seed each open so a prior attempt doesn't leak in.
  useEffect(() => {
    if (!open) return;
    const initial: Record<string, string> = {};
    for (const key of userApp.credential_keys) {
      initial[key] = userApp.credential_values[key] ?? "";
    }
    setValues(initial);
    setError(null);
  }, [open, userApp]);

  const canSave =
    userApp.credential_keys.length > 0 &&
    userApp.credential_keys.every((k) => (values[k] ?? "").trim().length > 0) &&
    !isSaving;

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      await upsertUserCredentials(userApp.id, values);
      onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  }

  const Logo = getAppTypeLogo(userApp.app_type);

  return (
    <Modal open={open} onOpenChange={(o) => !o && onClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={Logo}
          title={`Connect ${userApp.name}`}
          description="Enter your credentials to authorize this app for your account."
        />
        <Modal.Body>
          <div className="flex flex-col gap-4 w-full">
            <div className="flex flex-col gap-3 w-full">
              {userApp.credential_keys.map((key) => (
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
            <Button onClick={save} disabled={!canSave}>
              {isSaving ? "Connecting…" : "Connect"}
            </Button>
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
