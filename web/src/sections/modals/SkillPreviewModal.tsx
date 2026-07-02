"use client";

import { useEffect, useState } from "react";
import useSWR from "swr";
import { Button, CompactMarkdown, MessageCard, Text } from "@opal/components";
import { SvgBlocks, SvgSimpleLoader } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SkillPreview } from "@/lib/skills/types";
import InstructionsDisplayModeToggle, {
  type InstructionsDisplayMode,
} from "@/sections/skills/InstructionsDisplayModeToggle";

interface SkillPreviewModalProps {
  open: boolean;
  skillId: string | null;
  fallbackTitle?: string;
  onClose: () => void;
}

function metadataRows(
  preview: SkillPreview
): { label: string; value: string }[] {
  const rows: { label: string; value: string }[] = [];
  if (preview.source === "builtin") {
    rows.push({ label: "Created by", value: "Onyx" });
  } else if (preview.author_email) {
    rows.push({ label: "Created by", value: preview.author_email });
  }
  return rows;
}

export default function SkillPreviewModal({
  open,
  skillId,
  fallbackTitle = "Skill preview",
  onClose,
}: SkillPreviewModalProps) {
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("rendered");
  const swrKey = open && skillId ? SWR_KEYS.userSkillPreview(skillId) : null;
  const {
    data: preview,
    error,
    isLoading,
  } = useSWR<SkillPreview>(swrKey, errorHandlingFetcher);
  const instructionsMarkdown =
    preview?.instructions_markdown || "No instructions found.";

  useEffect(() => {
    if (open) {
      setInstructionsDisplayMode("rendered");
    }
  }, [open, skillId]);

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && onClose()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          icon={SvgBlocks}
          title={preview?.name ?? fallbackTitle}
          description={preview?.description}
          onClose={onClose}
        />
        <Modal.Body>
          {isLoading && (
            <div className="flex items-center justify-center min-h-40">
              <SvgSimpleLoader />
            </div>
          )}

          {error && !isLoading && (
            <MessageCard
              variant="error"
              title="Failed to load skill"
              description="Try closing and opening the preview again."
            />
          )}

          {preview && !isLoading && !error && (
            <Section gap={1} alignItems="stretch">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {metadataRows(preview).map((row) => (
                  <div key={row.label} className="flex flex-col gap-1">
                    <Text font="main-ui-action" color="text-05">
                      {row.label}
                    </Text>
                    <Text font="main-ui-body" color="text-04">
                      {row.value}
                    </Text>
                  </div>
                ))}
              </div>

              <Section gap={0.25} alignItems="stretch">
                <div className="flex items-center justify-between gap-2">
                  <Text font="main-ui-action" color="text-05">
                    Instructions
                  </Text>
                  <InstructionsDisplayModeToggle
                    value={instructionsDisplayMode}
                    onChange={setInstructionsDisplayMode}
                  />
                </div>
                <div className="rounded-lg border border-border p-3 overflow-y-auto overflow-x-hidden bg-background-neutral-00 max-h-[48dvh]">
                  {instructionsDisplayMode === "rendered" ? (
                    <CompactMarkdown>{instructionsMarkdown}</CompactMarkdown>
                  ) : (
                    <pre className="m-0 whitespace-pre-wrap wrap-break-word font-mono text-xs leading-5 text-text-04">
                      {instructionsMarkdown}
                    </pre>
                  )}
                </div>
              </Section>
            </Section>
          )}
        </Modal.Body>
        <Modal.Footer>
          <Button onClick={onClose}>Close</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
