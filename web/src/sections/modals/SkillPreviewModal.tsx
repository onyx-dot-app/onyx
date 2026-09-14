"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, CompactMarkdown, MessageCard, Text } from "@opal/components";
import { SvgBlocks, SvgSimpleLoader } from "@opal/icons";
import { Modal } from "@opal/components";
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
  unavailableReason?: string | null;
  onClose: () => void;
}

// Message keys under `skills.modals`, not copy — the literal union keeps `t()`
// statically checked while this stays a plain helper.
type MetadataLabelKey =
  | "preview.metadata.createdBy.label"
  | "preview.metadata.externalApp.label";

interface MetadataRow {
  labelKey: MetadataLabelKey;
  value: string;
}

function metadataRows(preview: SkillPreview): MetadataRow[] {
  const rows: MetadataRow[] = [];
  if (preview.source === "builtin") {
    rows.push({ labelKey: "preview.metadata.createdBy.label", value: "Onyx" });
  } else if (preview.author_email) {
    rows.push({
      labelKey: "preview.metadata.createdBy.label",
      value: preview.author_email,
    });
  }
  if (preview.external_app) {
    rows.push({
      labelKey: "preview.metadata.externalApp.label",
      value: preview.external_app.name,
    });
  }
  return rows;
}

export default function SkillPreviewModal({
  open,
  skillId,
  fallbackTitle,
  unavailableReason = null,
  onClose,
}: SkillPreviewModalProps) {
  const t = useTranslations("skills.modals");
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("rendered");
  const swrKey = open && skillId ? SWR_KEYS.userSkillPreview(skillId) : null;
  const {
    data: preview,
    error,
    isLoading,
  } = useSWR<SkillPreview>(swrKey, errorHandlingFetcher);
  const instructionsMarkdown =
    preview?.instructions_markdown || t("preview.noInstructions.message");
  const dependency = preview?.external_app;
  const dependencyUnavailableReason =
    dependency && !dependency.ready
      ? dependency.enabled
        ? t("preview.unavailable.appNotConnected", { appName: dependency.name })
        : t("preview.unavailable.appDisabled", { appName: dependency.name })
      : null;
  const displayedUnavailableReason =
    unavailableReason ?? dependencyUnavailableReason;

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
          title={preview?.name ?? fallbackTitle ?? t("preview.fallbackTitle")}
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
              title={t("preview.loadError.title")}
              description={t("preview.loadError.description")}
            />
          )}

          {preview && !isLoading && !error && (
            <Section gap={4} alignItems="stretch">
              {displayedUnavailableReason && (
                <MessageCard
                  variant="warning"
                  title={t("preview.unavailable.title")}
                  description={displayedUnavailableReason}
                />
              )}

              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {metadataRows(preview).map((row) => (
                  <div key={row.labelKey} className="flex flex-col gap-1">
                    <Text font="main-ui-action" color="text-05">
                      {t(row.labelKey)}
                    </Text>
                    <Text font="main-ui-body" color="text-04">
                      {row.value}
                    </Text>
                  </div>
                ))}
              </div>

              <Section gap={1} alignItems="stretch">
                <div className="flex items-center justify-between gap-2">
                  <Text font="main-ui-action" color="text-05">
                    {t("preview.instructions.title")}
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
          <Button onClick={onClose}>{t("preview.closeButton.label")}</Button>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
