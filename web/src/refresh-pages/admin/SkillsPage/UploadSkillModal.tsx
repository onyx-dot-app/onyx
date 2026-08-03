"use client";

import { useRef, useState } from "react";
import { Button } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import SkillSharePicker from "@/refresh-pages/admin/SkillsPage/SkillSharePicker";
import { createCustomSkill } from "@/lib/skills/api";
import { toast } from "@/hooks/useToast";
import { useUser } from "@/providers/UserProvider";
import { hasPermission } from "@/lib/permissions";
import { Permission } from "@/lib/types";

interface UploadSkillModalProps {
  open: boolean;
  onClose: () => void;
  /** Invoked after a successful upload so callers can refresh their list. */
  onUploaded: () => void;
}

export default function UploadSkillModal({
  open,
  onClose,
  onUploaded,
}: UploadSkillModalProps) {
  // Publish is global MANAGE_SKILLS; read effective (global) permissions, not
  // adminCapabilities — the scoped bundle would over-grant a group manager.
  const { permissions } = useUser();
  const canPublish = hasPermission(permissions, Permission.MANAGE_SKILLS);

  const [file, setFile] = useState<File | null>(null);
  // Default private for scoped managers; the server 403s their public create.
  const [isPublic, setIsPublic] = useState(canPublish);
  const [groupIds, setGroupIds] = useState<number[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Always-mounted modal: the useState above can capture a stale canPublish while permissions
  // are still loading. Re-sync the default each time the dialog opens (by then permissions have
  // loaded). Done during render, not in an effect, so the picker's tab mounts from the corrected
  // value instead of a frame late.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setIsPublic(canPublish);
    }
  }

  function reset() {
    setFile(null);
    setIsPublic(canPublish);
    setGroupIds([]);
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
      const created = await createCustomSkill({
        bundle: file,
        is_public: isPublic,
        // Org-wide skills don't carry group grants — keep the DB clean of
        // grants that would be ignored by the visibility filter anyway.
        group_ids: isPublic ? [] : groupIds,
      });
      toast.success(`Uploaded "${created.name}"`);
      reset();
      onUploaded();
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
          <Section gap={1} alignItems="stretch">
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

            <Section gap={0.5} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Share
              </Text>
              <SkillSharePicker
                isPublic={isPublic}
                onIsPublicChange={setIsPublic}
                groupIds={groupIds}
                onGroupIdsChange={setGroupIds}
                canPublish={canPublish}
              />
            </Section>
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
            {submitting ? "Uploading…" : "Upload"}
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
