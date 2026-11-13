"use client";

import type { RichStr } from "@opal/types";
import { IconLoader } from "@opal/loaders";
import { useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import { Button, CompactMarkdown, MessageCard, Text } from "@opal/components";
import { SvgBlocks } from "@opal/icons";
import { Modal } from "@opal/components";
import { CardGrid, Section } from "@opal/layouts";
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

interface SkillPreviewContentProps extends Omit<
  SkillPreviewModalProps,
  "open"
> {
  closeLabel?: string | RichStr;
}

type SkillPreviewDetailsProps = Pick<
  SkillPreviewModalProps,
  "skillId" | "unavailableReason"
>;

interface SkillInstructionsPanelProps {
  instructionsMarkdown: string;
}

export function SkillInstructionsPanel({
  instructionsMarkdown,
}: SkillInstructionsPanelProps) {
  const t = useTranslations("skills.modals");
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("rendered");
  return (
    <Section gap={1} height="auto" alignItems="stretch">
      <Section
        flexDirection="row"
        justifyContent="between"
        height="auto"
        gap={2}
      >
        <Text font="main-ui-action" color="text-05">
          {t("preview.instructions.title")}
        </Text>
        <InstructionsDisplayModeToggle
          value={instructionsDisplayMode}
          onChange={setInstructionsDisplayMode}
        />
      </Section>
      <Section
        height="auto"
        padding={3}
        gap={0}
        alignItems="stretch"
        className="rounded-lg border border-border overflow-y-auto overflow-x-hidden bg-background-neutral-00 max-h-[48dvh]"
      >
        {instructionsDisplayMode === "rendered" ? (
          <CompactMarkdown>{instructionsMarkdown}</CompactMarkdown>
        ) : (
          <pre className="m-0 whitespace-pre-wrap wrap-break-word font-mono text-xs leading-5 text-text-04">
            {instructionsMarkdown}
          </pre>
        )}
      </Section>
    </Section>
  );
}

export function SkillPreviewDetails({
  skillId,
  unavailableReason = null,
}: SkillPreviewDetailsProps) {
  const t = useTranslations("skills.modals");
  const swrKey = skillId ? SWR_KEYS.userSkillPreview(skillId) : null;
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

  return (
    <>
      {isLoading && (
        <Section height="auto" className="min-h-40">
          <IconLoader />
        </Section>
      )}

      {error && !isLoading && (
        <MessageCard
          outerPadding={1}
          innerPadding={1}
          variant="error"
          title={t("preview.loadError.title")}
          description={t("preview.loadError.description")}
        />
      )}

      {preview && !isLoading && !error && (
        <Section gap={4} height="auto" alignItems="stretch">
          {displayedUnavailableReason && (
            <MessageCard
              outerPadding={1}
              innerPadding={1}
              variant="warning"
              title={t("preview.unavailable.title")}
              description={displayedUnavailableReason}
            />
          )}

          <CardGrid>
            {metadataRows(preview).map((row) => (
              <Section
                key={row.labelKey}
                height="auto"
                gap={1}
                alignItems="stretch"
              >
                <Text font="main-ui-action" color="text-05">
                  {t(row.labelKey)}
                </Text>
                <Text font="main-ui-body" color="text-04">
                  {row.value}
                </Text>
              </Section>
            ))}
          </CardGrid>

          <SkillInstructionsPanel
            key={skillId}
            instructionsMarkdown={instructionsMarkdown}
          />
        </Section>
      )}
    </>
  );
}

export function SkillPreviewContent({
  skillId,
  fallbackTitle,
  unavailableReason = null,
  onClose,
  closeLabel,
}: SkillPreviewContentProps) {
  const t = useTranslations("skills.modals");
  const { data: preview } = useSWR<SkillPreview>(
    skillId ? SWR_KEYS.userSkillPreview(skillId) : null,
    errorHandlingFetcher
  );
  return (
    <>
      <Modal.Header
        icon={SvgBlocks}
        title={preview?.name ?? fallbackTitle ?? t("preview.fallbackTitle")}
        description={preview?.description}
        onClose={onClose}
      />
      <Modal.Body>
        <SkillPreviewDetails
          skillId={skillId}
          unavailableReason={unavailableReason}
        />
      </Modal.Body>
      <Modal.Footer>
        <Button onClick={onClose}>
          {closeLabel ?? t("preview.closeButton.label")}
        </Button>
      </Modal.Footer>
    </>
  );
}

export default function SkillPreviewModal({
  open,
  ...props
}: SkillPreviewModalProps) {
  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && props.onClose()}>
      <Modal.Content width="lg" height="lg">
        <SkillPreviewContent {...props} />
      </Modal.Content>
    </Modal>
  );
}
