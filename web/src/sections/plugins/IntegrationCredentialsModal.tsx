"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  BasicModalFooter,
  Button,
  InputPasswordTypeIn,
  InputTypeIn,
  Modal,
} from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import { SvgKey } from "@opal/icons";
import { saveUserConnection } from "@/lib/integrations/svc";
import type { MemberIntegration } from "@/lib/integrations/types";

interface IntegrationCredentialsModalProps {
  integration: MemberIntegration;
  onClose: () => void;
  onConnected: () => void;
}

/** The API key form of one integration, made from its credential fields. */
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
          {fields.map((field) => {
            const Input = field.secret ? InputPasswordTypeIn : InputTypeIn;
            return (
              <InputVertical
                key={field.key}
                withLabel={`credential-${field.key}`}
                title={field.label}
                error={
                  showErrors && !values[field.key]?.trim()
                    ? t("required")
                    : undefined
                }
              >
                <Input
                  id={`credential-${field.key}`}
                  aria-label={field.label}
                  value={values[field.key] ?? ""}
                  disabled={busy}
                  onChange={(event) =>
                    setValues((current) => ({
                      ...current,
                      [field.key]: event.target.value,
                    }))
                  }
                />
              </InputVertical>
            );
          })}
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" disabled={busy} onClick={onClose}>
                {t("cancel")}
              </Button>
            }
            submit={
              <Button disabled={busy} onClick={() => void submit()}>
                {busy ? t("connecting") : t("submit")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
