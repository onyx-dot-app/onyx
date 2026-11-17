"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { BasicModalFooter, Button, Modal } from "@opal/components";
import { toast } from "@opal/layouts";
import { SvgKey } from "@opal/icons";
import { saveUserConnection } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";
import CredentialFieldInputs from "@/sections/integrations/CredentialFieldInputs";

interface IntegrationCredentialsModalProps {
  integration: MemberIntegration;
  onClose: () => void;
  onConnected: () => void;
}

export default function IntegrationCredentialsModal({
  integration,
  onClose,
  onConnected,
}: IntegrationCredentialsModalProps) {
  const t = useTranslations("plugins.member.credentials");
  const [values, setValues] = useState<Record<string, string>>({});
  const [showErrors, setShowErrors] = useState(false);
  const [busy, setBusy] = useState(false);
  const fields = integration.credential_fields;

  async function submit() {
    if (fields.some((field) => !values[field.key]?.trim())) {
      setShowErrors(true);
      return;
    }
    setBusy(true);
    try {
      const status = await saveUserConnection(
        integration.id,
        Object.fromEntries(
          fields.map((field) => [field.key, values[field.key] ?? ""])
        )
      );
      if (status.state !== "connected") {
        toast.error(status.reason ?? t("failed"));
        return;
      }
      onConnected();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("failed"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open onOpenChange={(open) => !open && !busy && onClose()}>
      <Modal.Content width="sm" preventAccidentalClose={false}>
        <Modal.Header
          icon={SvgKey}
          title={t("title", { name: integration.name })}
          description={t("description")}
          onClose={busy ? undefined : onClose}
        />
        <Modal.Body padding={4} gap={4} alignItems="stretch">
          <CredentialFieldInputs
            fields={fields}
            values={values}
            onChange={setValues}
            disabled={busy}
            error={(field) =>
              showErrors && !values[field.key]?.trim()
                ? t("required")
                : undefined
            }
          />
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" disabled={busy} onClick={onClose}>
                {t("cancel.label")}
              </Button>
            }
            submit={
              <Button disabled={busy} onClick={() => void submit()}>
                {busy ? t("submit.pendingLabel") : t("submit.label")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
