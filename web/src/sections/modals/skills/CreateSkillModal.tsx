"use client";

import { useEffect, useState } from "react";
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
  validateDraft?: (draft: SkillCreationDraft) => string | null;
}

interface CreateSkillModalContentProps extends Omit<
  CreateSkillModalProps,
  "open" | "onClose"
> {
  hidden?: boolean;
  onRequestClose: () => void;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  preserveDraftOnContinue?: boolean;
}

export function CreateSkillModalContent({
  hidden = false,
  onRequestClose,
  onContinue,
  onBusyChange,
  onDirtyChange,
  preserveDraftOnContinue = false,
  validateDraft,
}: CreateSkillModalContentProps) {
  const [bundle, setBundle] = useState<PreparedSkillBundle | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const busy = preparing || inspecting;

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  function reset() {
    setBundle(null);
    setErrorMessage(null);
    onDirtyChange?.(false);
  }

  function handleClose() {
    if (busy) return;
    onRequestClose();
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
      const validationError = validateDraft?.(draft);
      if (validationError) {
        setErrorMessage(validationError);
        return;
      }
      if (!preserveDraftOnContinue) reset();
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

  if (hidden) return null;

  return (
    <>
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
            onDirtyChange?.(nextBundle !== null);
          }}
          onError={(message) => {
            setBundle(null);
            setErrorMessage(message);
            onDirtyChange?.(false);
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
        <Button prominence="secondary" disabled={busy} onClick={handleClose}>
          Cancel
        </Button>
        <Button
          disabled={busy || !bundle}
          onClick={() => void handleContinue()}
          icon={SvgUploadCloud}
        >
          {inspecting ? "Opening…" : "Review skill"}
        </Button>
      </Modal.Footer>
    </>
  );
}

export default function CreateSkillModal({
  open,
  onClose,
  onContinue,
  validateDraft,
}: CreateSkillModalProps) {
  const [busy, setBusy] = useState(false);

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && !busy && onClose()}>
      <Modal.Content width="sm">
        <CreateSkillModalContent
          onRequestClose={onClose}
          onContinue={onContinue}
          onBusyChange={setBusy}
          validateDraft={validateDraft}
        />
      </Modal.Content>
    </Modal>
  );
}
