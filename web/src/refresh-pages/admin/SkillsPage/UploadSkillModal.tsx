"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { Section } from "@/layouts/general-layouts";
import VisibilityPicker from "@/refresh-pages/admin/SkillsPage/VisibilityPicker";
import type { SkillVisibility } from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface UploadSkillModalProps {
  open: boolean;
  onClose: () => void;
  /** Whether the user can pick org-wide visibility (admin only). */
  canSetOrgWide: boolean;
  /** Wireframe-only callback. */
  onUpload: (input: {
    file: File | null;
    slug: string;
    name: string;
    description: string;
    visibility: SkillVisibility;
  }) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UploadSkillModal({
  open,
  onClose,
  canSetOrgWide,
  onUpload,
}: UploadSkillModalProps) {
  const [file, setFile] = useState<File | null>(null);
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [visibility, setVisibility] = useState<SkillVisibility>("private");

  function handleFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const selected = event.target.files?.[0] ?? null;
    setFile(selected);
  }

  function handleSubmit() {
    onUpload({ file, slug, name, description, visibility });
    setFile(null);
    setSlug("");
    setName("");
    setDescription("");
    setVisibility("private");
  }

  const submitDisabled = !file || slug.trim() === "" || name.trim() === "";

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="md">
        <Modal.Header
          icon={SvgUploadCloud}
          title="Upload skill"
          description="Upload a zip bundle. SKILL.md must be at the root with name + description in frontmatter."
          onClose={onClose}
        />
        <Modal.Body>
          <Section gap={1} alignItems="stretch">
            <Section gap={0.25} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Bundle (.zip)
              </Text>
              <div className="flex items-center gap-2">
                <input
                  id="skill-bundle-file"
                  type="file"
                  accept=".zip,application/zip"
                  onChange={handleFileChange}
                  className="hidden"
                />
                <label htmlFor="skill-bundle-file">
                  <Button
                    icon={SvgUploadCloud}
                    prominence="secondary"
                    onClick={() => {
                      document.getElementById("skill-bundle-file")?.click();
                    }}
                  >
                    {file ? "Change file" : "Choose zip"}
                  </Button>
                </label>
                <Text as="span" mainUiBody text03>
                  {file ? file.name : "No file selected"}
                </Text>
              </div>
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Slug
              </Text>
              <InputTypeIn
                value={slug}
                onChange={(e) => setSlug(e.target.value)}
                placeholder="deal-summary"
              />
              <Text as="span" secondaryBody text03>
                Lowercase letters, numbers, and hyphens. Must match the
                frontmatter `name` in SKILL.md.
              </Text>
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Name
              </Text>
              <InputTypeIn
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Deal summary"
              />
            </Section>

            <Section gap={0.25} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Description
              </Text>
              <InputTextArea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="What this skill does, in one or two sentences."
                rows={3}
              />
              <Text as="span" secondaryBody text03>
                The agent reads this to decide whether to invoke the skill. Be
                specific about when it applies.
              </Text>
            </Section>

            <Section gap={0.5} alignItems="stretch">
              <Text as="span" mainUiAction text05>
                Visibility
              </Text>
              <VisibilityPicker
                visibility={visibility}
                onChange={setVisibility}
                canSetOrgWide={canSetOrgWide}
              />
            </Section>
          </Section>
        </Modal.Body>
        <Modal.Footer>
          <Button prominence="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={submitDisabled}
            onClick={handleSubmit}
            icon={SvgUploadCloud}
          >
            Upload
          </Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
