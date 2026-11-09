"use client";

import type { RichStr } from "@opal/types";
import { IconLoader } from "@opal/loaders";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR from "swr";
import {
  Button,
  CompactMarkdown,
  MessageCard,
  Tabs,
  Text,
} from "@opal/components";
import { SvgBlocks } from "@opal/icons";
import { Modal } from "@opal/components";
import { CardGrid, Section } from "@opal/layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { CustomSkill, SkillPreview } from "@/lib/skills/types";
import InstructionsDisplayModeToggle, {
  type InstructionsDisplayMode,
} from "@/sections/skills/InstructionsDisplayModeToggle";

import SkillVersions from "@/sections/skills/SkillVersions";
import { canReadSkillHistory } from "@/lib/skills/permissions";
import useScreenSize from "@opal/hooks/useScreenSize";

interface SkillPreviewModalProps {
  open: boolean;
  skillId: string | null;
  fallbackTitle?: string;
  unavailableReason?: string | null;
  onClose: () => void;
  historySkill?: CustomSkill;
  onRestored?: () => void;
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
  onBusyChange?: (busy: boolean) => void;
}

type SkillPreviewDetailsProps = Pick<
  SkillPreviewModalProps,
  "skillId" | "unavailableReason"
>;

export function SkillPreviewDetails({
  skillId,
  unavailableReason = null,
}: SkillPreviewDetailsProps) {
  const t = useTranslations("skills.modals");
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("rendered");
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

  useEffect(() => {
    setInstructionsDisplayMode("rendered");
  }, [skillId]);

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
  historySkill,
  onRestored,
  onBusyChange,
}: SkillPreviewContentProps) {
  const t = useTranslations("skills.modals");
  const { data: preview } = useSWR<SkillPreview>(
    skillId ? SWR_KEYS.userSkillPreview(skillId) : null,
    errorHandlingFetcher
  );
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState("details");
  const versionsCopy = useTranslations("skills.versions");
  const { isSmallScreen } = useScreenSize();
  const historyAllowed = historySkill && canReadSkillHistory(historySkill);
  const header = (
    <Modal.Header
      padding={isSmallScreen ? 0 : 2}
      reserveCloseSpace={isSmallScreen}
      icon={isSmallScreen ? undefined : SvgBlocks}
      title={preview?.name ?? fallbackTitle ?? t("preview.fallbackTitle")}
      description={tab === "versions" ? undefined : preview?.description}
      onClose={busy ? undefined : onClose}
    />
  );

  return (
    <>
      {!isSmallScreen && header}
      <Modal.Body padding={isSmallScreen ? 2 : 4}>
        {isSmallScreen && header}
        {historyAllowed ? (
          <Tabs
            variant="underline"
            value={tab}
            onValueChange={(value) => {
              if (!busy) setTab(value);
            }}
            gap={isSmallScreen ? 3 : 6}
          >
            <Tabs.List enableScrollArrows>
              <Tabs.Trigger value="details" disabled={busy}>
                {t("tabs.details")}
              </Tabs.Trigger>
              <Tabs.Trigger value="versions" disabled={busy}>
                {versionsCopy("title")}
              </Tabs.Trigger>
            </Tabs.List>
            <Tabs.Content value="details">
              <SkillPreviewDetails
                skillId={skillId}
                unavailableReason={unavailableReason}
              />
            </Tabs.Content>
            <Tabs.Content value="versions">
              <SkillVersions
                skill={historySkill}
                onBusyChange={(pending) => {
                  setBusy(pending);
                  onBusyChange?.(pending);
                }}
                onRestored={() => onRestored?.()}
              />
            </Tabs.Content>
          </Tabs>
        ) : (
          <SkillPreviewDetails
            skillId={skillId}
            unavailableReason={unavailableReason}
          />
        )}
      </Modal.Body>
      <Modal.Footer padding={isSmallScreen ? 2 : 4}>
        <Button disabled={busy} onClick={onClose}>
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
  const [busy, setBusy] = useState(false);
  return (
    <Modal
      open={open}
      onOpenChange={(isOpen) => !isOpen && !busy && props.onClose()}
    >
      <Modal.Content width="lg" height="lg">
        <SkillPreviewContent {...props} onBusyChange={setBusy} />
      </Modal.Content>
    </Modal>
  );
}
