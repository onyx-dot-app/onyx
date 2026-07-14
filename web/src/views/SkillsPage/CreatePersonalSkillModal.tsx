"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { createCustomSkill } from "@/lib/skills/api";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import { toast } from "@/hooks/useToast";
import SkillBundlePicker from "@/sections/skills/SkillBundlePicker";

interface CreatePersonalSkillModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a successful upload so callers can refresh their list. */
  onCreated: () => void;
}

export default function CreatePersonalSkillModal({
  open,
  onClose,
  onCreated,
}: CreatePersonalSkillModalProps) {
  const [bundle, setBundle] = useState<PreparedSkillBundle | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  function reset() {
    setBundle(null);
    setErrorMessage(null);
  }

  function handleClose() {
    if (preparing || submitting) return;
    reset();
    onClose();
  }

  async function handleSubmit() {
    if (!bundle) return;
    setSubmitting(true);
    setErrorMessage(null);
    try {
      const created = await createCustomSkill(bundle.file);
      toast.success(`Created "${created.name}"`);
      reset();
      onCreated();
      onClose();
    } catch (err) {
      console.error("Failed to create personal skill", err);
      // Surface the server detail (duplicate slug, reserved slug, cap reached)
      // inline so the user can act on it.
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to create skill"
      );
    } finally {
      setSubmitting(false);
    }
  }

  const submitDisabled = submitting || !bundle;

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Create skill"
          description="Add a personal skill from a ZIP file or folder. Only you can access it."
          onClose={handleClose}
        />
        <Modal.Body>
          <SkillBundlePicker
            value={bundle}
            disabled={submitting}
            onPreparingChange={setPreparing}
            onChange={(nextBundle) => {
              setBundle(nextBundle);
              setErrorMessage(null);
            }}
            onError={setErrorMessage}
          />
          {errorMessage && (
            <div className="mt-2">
              <Text as="p" font="secondary-body" color="status-error-05">
                {errorMessage}
              </Text>
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button
            prominence="secondary"
            disabled={preparing || submitting}
            onClick={handleClose}
          >
            Cancel
          </Button>
          <Button
            disabled={preparing || submitDisabled}
            onClick={handleSubmit}
            icon={SvgUploadCloud}
          >
            {submitting ? "Creating…" : "Create"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
