"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  BasicModalFooter,
  Button,
  InputTextArea,
  InputTypeIn,
  Modal,
} from "@opal/components";
import { InputVertical, toast } from "@opal/layouts";
import { SvgEdit } from "@opal/icons";
import { updateIntegration } from "@/lib/integrations/svc";
import type { AdminIntegrationDetail } from "@/lib/integrations/types";

interface EditIntegrationDetailsModalProps {
  integration: AdminIntegrationDetail;
  onClose: () => void;
  onSaved: () => Promise<void>;
}

/** Edits the name and description of an integration. */
export default function EditIntegrationDetailsModal({
  integration,
  onClose,
  onSaved,
}: EditIntegrationDetailsModalProps) {
  const t = useTranslations("admin.integrations.detail.overview.details");
  const [name, setName] = useState(integration.name);
  const [description, setDescription] = useState(integration.description ?? "");
  const [busy, setBusy] = useState(false);
  const dirty =
    name !== integration.name ||
    description !== (integration.description ?? "");

  async function save() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await updateIntegration(integration.id, {
        name: name.trim(),
        description: description.trim() || null,
      });
      await onSaved();
      toast.success(t("saved"));
      onClose();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("saveFailed"));
      setBusy(false);
    }
  }

  return (
    <Modal open onOpenChange={(open) => !open && !busy && onClose()}>
      <Modal.Content width="sm">
        <Modal.Header icon={SvgEdit} title={t("title")} onClose={onClose} />
        <Modal.Body padding={4} gap={4} alignItems="stretch">
          <InputVertical
            title={t("name")}
            error={name.trim() ? undefined : t("nameRequired")}
          >
            <InputTypeIn
              aria-label={t("name")}
              value={name}
              variant={busy ? "disabled" : "primary"}
              onChange={(event) => setName(event.target.value)}
            />
          </InputVertical>
          <InputVertical title={t("description")} suffix="optional">
            <InputTextArea
              aria-label={t("description")}
              value={description}
              rows={3}
              variant={busy ? "disabled" : "primary"}
              onChange={(event) => setDescription(event.target.value)}
            />
          </InputVertical>
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="secondary" disabled={busy} onClick={onClose}>
                {t("cancel")}
              </Button>
            }
            submit={
              <Button
                disabled={busy || !dirty || !name.trim()}
                onClick={() => void save()}
              >
                {t("save")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
