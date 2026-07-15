"use client";

import { useState } from "react";
import { Button, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { toast } from "@opal/layouts";
import { createCustomSkill } from "@/lib/skills/api";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import type { CustomSkill } from "@/lib/skills/types";
import Modal from "@/refresh-components/Modal";
import SkillBundlePicker from "@/sections/skills/SkillBundlePicker";

interface CreateSkillModalProps {
  open: boolean;
  onClose: () => void;
  onCreated: (skill: CustomSkill) => void;
}

export default function CreateSkillModal({
  open,
  onClose,
  onCreated,
}: CreateSkillModalProps) {
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
      onCreated(created);
      onClose();
    } catch (error) {
      console.error("Failed to create skill", error);
      setErrorMessage(
        error instanceof Error ? error.message : "Failed to create skill"
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Create skill"
          description="Upload a SKILL.md file, ZIP file, or skill folder. New skills are private until you choose to share them."
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
            onError={(message) => {
              setBundle(null);
              setErrorMessage(message);
            }}
          />
          <div className="mt-3">
            <Text as="p" font="main-ui-body" color="text-02">
              File requirements
            </Text>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              <Text as="li" font="secondary-body" color="text-03">
                SKILL.md must include valid frontmatter with a name and
                description.
              </Text>
              <Text as="li" font="secondary-body" color="text-03">
                ZIP files must contain a SKILL.md file.
              </Text>
              <Text as="li" font="secondary-body" color="text-03">
                Upload one skill at a time.
              </Text>
            </ul>
          </div>
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
            disabled={preparing || submitting || !bundle}
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
