"use client";

import useSWR from "swr";
import {
  Button,
  CompactMarkdown,
  MessageCard,
  Tag,
  Text,
} from "@opal/components";
import { SvgBlocks, SvgSimpleLoader } from "@opal/icons";
import Modal from "@/refresh-components/Modal";
import { Section } from "@/layouts/general-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SkillPreview } from "@/views/admin/SkillsPage/interfaces";

type SkillPreviewMode = "admin" | "user";

interface SkillPreviewModalProps {
  open: boolean;
  mode: SkillPreviewMode;
  skillId: string | null;
  fallbackTitle?: string;
  onClose: () => void;
}

function statusTag(preview: SkillPreview) {
  if (preview.source === "builtin") {
    return <Tag title="Built-in" color="blue" />;
  }
  return <Tag title="Custom" color="gray" />;
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
  mode,
  skillId,
  fallbackTitle = "Skill preview",
  onClose,
}: SkillPreviewModalProps) {
  const swrKey =
    open && skillId
      ? mode === "admin"
        ? SWR_KEYS.adminSkillPreview(skillId)
        : SWR_KEYS.userSkillPreview(skillId)
      : null;
  const {
    data: preview,
    error,
    isLoading,
  } = useSWR<SkillPreview>(swrKey, errorHandlingFetcher);

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
                <div className="flex flex-col gap-1">
                  <Text font="main-ui-action" color="text-05">
                    Source
                  </Text>
                  <div className="flex flex-wrap items-center gap-1">
                    {statusTag(preview)}
                  </div>
                </div>
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
                <Text font="main-ui-action" color="text-05">
                  Instructions
                </Text>
                <div className="rounded-lg border border-border p-3 overflow-y-auto overflow-x-hidden bg-background-50 max-h-[48dvh]">
                  <CompactMarkdown>
                    {preview.instructions_markdown || "No instructions found."}
                  </CompactMarkdown>
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
