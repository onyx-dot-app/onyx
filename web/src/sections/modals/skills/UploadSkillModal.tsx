"use client";

import { useRef, useState } from "react";
import { Button } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import { createCustomSkill } from "@/lib/skills/api";
import { toast } from "@/hooks/useToast";
import type { CustomSkill } from "@/lib/skills/types";

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
  const [file, setFile] = useState<File | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function reset() {
    setFile(null);
    // Clear the native input too — otherwise re-selecting the same file
    // after a cancel fires no change event.
    if (fileInputRef.current) {
      fileInputRef.current.value = "";
    }
  }

  function handleClose() {
    if (submitting) return;
    reset();
    onClose();
  }

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
  }

  async function handleSubmit() {
    if (!file) return;
    setSubmitting(true);
    try {
      const created = await createCustomSkill(file);
      toast.success(`Uploaded "${created.name}"`);
      reset();
      onUploaded(created);
      onClose();
    } catch (err) {
      console.error("Failed to upload skill bundle", err);
      toast.error(err instanceof Error ? err.message : "Upload failed", {
        description: "Skill bundle was not saved.",
      });
    } finally {
      setSubmitting(false);
    }
  }

  const submitDisabled = submitting || !file;

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Upload skill"
          description="Upload a zip bundle. The zip filename becomes the slug, and SKILL.md frontmatter provides the name + description."
          onClose={handleClose}
        />
        <Modal.Body>
          <Section gap={0.25} alignItems="stretch">
            <Text as="span" mainUiAction text05>
              Bundle (.zip)
            </Text>
            <div className="flex items-center gap-2">
              <input
                ref={fileInputRef}
                type="file"
                accept=".zip,application/zip"
                onChange={handleFileChange}
                className="hidden"
              />
              <Button
                icon={SvgUploadCloud}
                prominence="secondary"
                onClick={() => fileInputRef.current?.click()}
              >
                {file ? "Change file" : "Choose zip"}
              </Button>
              <Text as="span" mainUiBody text03>
                {file ? file.name : "No file selected"}
              </Text>
            </div>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={handleClose}>
            Cancel
          </Button>
          <Button
            disabled={submitDisabled}
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
