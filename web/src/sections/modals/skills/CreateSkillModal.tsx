"use client";

import { useState } from "react";
import { Button, Modal, Text } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { inspectSkillBundle } from "@/lib/skills/api";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import type { SkillCreationDraft } from "@/lib/skills/creationDraft";
import SkillBundlePicker from "@/sections/skills/SkillBundlePicker";

interface CreateSkillModalProps {
  open: boolean;
  onClose: () => void;
  onContinue: (draft: SkillCreationDraft) => void;
}

export default function CreateSkillModal({
  open,
  onClose,
  onContinue,
}: CreateSkillModalProps) {
  const [bundle, setBundle] = useState<PreparedSkillBundle | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  function reset() {
    setBundle(null);
    setErrorMessage(null);
  }

  function handleClose() {
    if (preparing || inspecting) return;
    reset();
    onClose();
  }

  async function handleContinue() {
    if (!bundle) return;
    setInspecting(true);
    setErrorMessage(null);
    try {
      const contents = await inspectSkillBundle(bundle.file);
      const draft: SkillCreationDraft = {
        contents,
        upload: {
          file: bundle.file,
          displayName: bundle.displayName,
          entries: contents.files,
          containsSkillMd: true,
        },
      };
      reset();
      onContinue(draft);
    } catch (error) {
      console.error("Failed to inspect skill bundle", error);
      setErrorMessage(
        error instanceof Error ? error.message : "Failed to read skill"
      );
    } finally {
      setInspecting(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && handleClose()}>
      <Modal.Content width="sm">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Upload skill"
          description="Upload a SKILL.md file, ZIP file, or skill folder. You can review and edit its details before saving."
          onClose={handleClose}
        />
        <Modal.Body>
          <SkillBundlePicker
            value={bundle}
            disabled={inspecting}
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
            <div role="alert" className="mt-2">
              <Text as="p" font="secondary-body" color="status-error-05">
                {errorMessage}
              </Text>
            </div>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button
            prominence="secondary"
            disabled={preparing || inspecting}
            onClick={handleClose}
          >
            Cancel
          </Button>
          <Button
            disabled={preparing || inspecting || !bundle}
            onClick={() => void handleContinue()}
            icon={SvgUploadCloud}
          >
            {inspecting ? "Opening…" : "Review skill"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
