"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { createCustomSkill } from "@/lib/skills/api";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import { toast } from "@/hooks/useToast";
import type { CustomSkill } from "@/lib/skills/types";
import SkillBundlePicker from "@/sections/skills/SkillBundlePicker";

interface UploadSkillModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked with the created skill after a successful upload. */
  onUploaded: (skill: CustomSkill) => void;
}

export default function UploadSkillModal({
  open,
  onClose,
  onUploaded,
}: UploadSkillModalProps) {
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
    try {
      const created = await createCustomSkill(bundle.file);
      toast.success(`Uploaded "${created.name}"`);
      reset();
      onUploaded(created);
      onClose();
    } catch (err) {
      console.error("Failed to upload skill bundle", err);
      setErrorMessage(err instanceof Error ? err.message : "Upload failed");
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
          title="Upload skill"
          description="Add a skill from a ZIP file or folder. SKILL.md provides its name and description."
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
            {submitting ? "Uploading..." : "Upload"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
