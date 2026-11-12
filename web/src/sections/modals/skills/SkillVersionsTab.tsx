"use client";

import { useState, type ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { IconLoader } from "@opal/loaders";
import {
  Badge,
  Button,
  MessageCard,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { SvgArrowLeft, SvgHistory } from "@opal/icons";
import { errorHandlingFetcher, fetchErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  isSkillVersionStale,
  publishSkill,
  restoreSkillVersion,
} from "@/lib/skills/api";
import { hasUnpublishedChanges } from "@/lib/skills/sharing";
import { usePublishAction } from "@/lib/skills/hooks";
import type {
  CustomSkill,
  SkillEditableDetail,
  SkillVersion,
  SkillVersionPreview,
} from "@/lib/skills/types";
import { SkillInstructionsPanel } from "@/sections/modals/SkillPreviewModal";

interface SkillVersionsTabProps {
  skill: CustomSkill;
  /** The author or an organization-wide manager: may publish an update. */
  canPublish: boolean;
  /** Called after a restore or a publish changes the skill. */
  onChanged: () => void;
  /** Called with the new current version after a restore. */
  onRestored?: (restored: SkillEditableDetail) => void;
  /** The open editor has unsaved changes that a restore would replace. */
  restoreBlocked?: boolean;
}

function canRestore(version: SkillVersion): boolean {
  return version.bundle_kept && !version.is_current;
}

export default function SkillVersionsTab({
  skill,
  canPublish,
  onChanged,
  onRestored,
  restoreBlocked = false,
}: SkillVersionsTabProps) {
  const skillId = skill.id;
  const t = useTranslations("skills.modals.versions");
  const editorCopy = useTranslations("skills.editor");
  const format = useFormatter();
  const [previewVersionId, setPreviewVersionId] = useState<string | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const [isStale, setIsStale] = useState(false);
  const [publishing, setPublishing] = useState(false);
  const publishAction = usePublishAction();
  const {
    data: versions = [],
    error,
    isLoading,
    mutate: refreshVersions,
  } = useSWR<SkillVersion[], Error>(
    SWR_KEYS.skillVersions(skillId),
    errorHandlingFetcher
  );
  const currentVersion = versions.find((version) => version.is_current);
  const previewVersion =
    versions.find((version) => version.id === previewVersionId) ?? null;

  async function handleRestore(version: SkillVersion) {
    if (!currentVersion || restoringId !== null || restoreBlocked) return;
    setRestoringId(version.id);
    try {
      const restored = await restoreSkillVersion(
        skillId,
        version.id,
        currentVersion.id
      );
      if (restored.current_version_id === currentVersion.id) {
        toast.info(
          t("restore.unchangedToast", { number: version.version_number })
        );
      } else {
        toast.success(
          t("restore.successToast", {
            number: version.version_number,
            newNumber: restored.current_version_number ?? 0,
          })
        );
        onRestored?.(restored);
        onChanged();
      }
      setPreviewVersionId(null);
      await refreshVersions();
    } catch (err) {
      if (isSkillVersionStale(err)) {
        setIsStale(true);
        return;
      }
      console.error("Failed to restore skill version", err);
      toast.error(
        err instanceof Error ? err.message : t("restore.failedToast")
      );
    } finally {
      setRestoringId(null);
    }
  }

  async function handlePublishUpdate() {
    if (!currentVersion || publishing) return;
    setPublishing(true);
    try {
      const published = await publishSkill(skillId, currentVersion.id);
      if (
        published.published_version_number === currentVersion.version_number
      ) {
        toast.success(
          t("publishUpdate.successToast", {
            number: currentVersion.version_number,
          })
        );
      } else if (
        published.pending_version_number === currentVersion.version_number
      ) {
        toast.info(
          t("publishUpdate.sentForReviewToast", {
            number: currentVersion.version_number,
          })
        );
      }
      onChanged();
      await refreshVersions();
    } catch (err) {
      if (isSkillVersionStale(err)) {
        setIsStale(true);
        return;
      }
      console.error("Failed to publish skill update", err);
      toast.error(
        err instanceof Error ? err.message : t("publishUpdate.failedToast")
      );
    } finally {
      setPublishing(false);
    }
  }

  async function handleReloadStale() {
    await refreshVersions();
    onChanged();
    setIsStale(false);
  }

  const unpublishedChanges = hasUnpublishedChanges(skill);
  const isPending =
    skill.pending_version_number !== null &&
    skill.pending_version_number === skill.current_version_number;

  function restoreButton(version: SkillVersion) {
    if (!canRestore(version)) return null;
    return (
      <Button
        prominence="secondary"
        size="sm"
        icon={SvgHistory}
        disabled={restoringId !== null || isStale || restoreBlocked}
        aria-label={t("restore.ariaLabel", { number: version.version_number })}
        onClick={() => void handleRestore(version)}
      >
        {t("restore.label")}
      </Button>
    );
  }

  const columns: TableColumn<SkillVersion>[] = [
    {
      kind: "data",
      field: "version_number",
      title: t("columns.version"),
      weight: 24,
      cell: (versionNumber, row) => (
        <Section
          flexDirection="row"
          justifyContent="start"
          gap={1}
          height="auto"
        >
          <Text font="main-ui-action" color="text-04">
            {t("versionLabel", { number: versionNumber })}
          </Text>
          {row.is_current && <Badge title={t("currentBadge")} color="info" />}
          {row.review_status === "published" && (
            <Badge title={t("status.published")} color="success" />
          )}
          {row.review_status === "pending" && (
            <Badge title={t("status.pending")} color="pending" />
          )}
          {row.review_status === "denied" && (
            <Badge title={t("status.denied")} color="error" />
          )}
        </Section>
      ),
    },
    {
      kind: "data",
      field: "created_by_email",
      title: t("columns.madeBy"),
      weight: 30,
      truncate: true,
      cell: (email) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {email ?? t("unknownAuthor")}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "created_at",
      title: t("columns.date"),
      weight: 28,
      cell: (createdAt) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {format.dateTime(new Date(createdAt), {
            dateStyle: "medium",
            timeStyle: "short",
          })}
        </Text>
      ),
    },
    {
      kind: "actions",
      showColumnVisibility: false,
      showSorting: false,
      cell: (row) => restoreButton(row),
    },
  ];

  if (isLoading) {
    return (
      <Section height="auto" className="min-h-40">
        <IconLoader />
      </Section>
    );
  }

  if (error) {
    return (
      <MessageCard
        outerPadding={1}
        innerPadding={1}
        variant="error"
        title={t("loadError.title")}
        description={t("loadError.description")}
      />
    );
  }

  return (
    <Section gap={4} height="auto" alignItems="stretch">
      {restoreBlocked && (
        <MessageCard
          variant="warning"
          title={t("restore.unsavedChanges.title")}
          description={t("restore.unsavedChanges.description")}
        />
      )}
      {isStale && (
        <MessageCard
          variant="warning"
          title={editorCopy("staleVersion.title")}
          description={editorCopy("staleVersion.description")}
          rightChildren={
            <Button
              type="button"
              prominence="secondary"
              onClick={() => void handleReloadStale()}
            >
              {editorCopy("staleVersion.reload.label")}
            </Button>
          }
        />
      )}
      {(unpublishedChanges || (canPublish && isPending)) && (
        <Section
          flexDirection="row"
          justifyContent="between"
          height="auto"
          gap={2}
          wrap
        >
          <Section
            flexDirection="row"
            justifyContent="start"
            width="auto"
            height="auto"
            gap={1}
            wrap
          >
            {unpublishedChanges && (
              <Badge title={t("unpublishedBadge")} color="warning" size={5} />
            )}
            {skill.published_version_number !== null && (
              <Text font="secondary-body" color="text-03">
                {t("organizationRuns", {
                  number: skill.published_version_number,
                })}
              </Text>
            )}
          </Section>
          {canPublish &&
            (isPending ? (
              <Badge title={t("waitingForReview")} color="pending" size={6} />
            ) : unpublishedChanges && publishAction === "off" ? (
              <Text font="secondary-body" color="text-03">
                {t("publishUpdate.offNotice")}
              </Text>
            ) : unpublishedChanges ? (
              <Button
                disabled={publishing || isStale || !currentVersion}
                onClick={() => void handlePublishUpdate()}
              >
                {t("publishUpdate.label")}
              </Button>
            ) : null)}
        </Section>
      )}
      {previewVersion ? (
        <SkillVersionPreviewView
          skillId={skillId}
          version={previewVersion}
          onBack={() => setPreviewVersionId(null)}
          restoreAction={restoreButton(previewVersion)}
        />
      ) : (
        <Table
          label={t("tableLabel")}
          items={versions}
          columns={columns}
          getRowId={(row) => row.id}
          pageSize={false}
          size={2.25}
          onRowClick={(row) => setPreviewVersionId(row.id)}
          getRowLabel={(row) =>
            t("previewRow.ariaLabel", { number: row.version_number })
          }
        />
      )}
    </Section>
  );
}

interface SkillVersionPreviewViewProps {
  skillId: string;
  version: SkillVersion;
  onBack: () => void;
  restoreAction: ReactNode;
}

function SkillVersionPreviewView({
  skillId,
  version,
  onBack,
  restoreAction,
}: SkillVersionPreviewViewProps) {
  const t = useTranslations("skills.modals");
  const {
    data: preview,
    error,
    isLoading,
  } = useSWR<SkillVersionPreview, Error>(
    SWR_KEYS.skillVersion(skillId, version.id),
    errorHandlingFetcher
  );

  return (
    <Section gap={4} height="auto" alignItems="stretch">
      <Section
        flexDirection="row"
        justifyContent="between"
        height="auto"
        gap={2}
      >
        <Button prominence="secondary" icon={SvgArrowLeft} onClick={onBack}>
          {t("versions.preview.back")}
        </Button>
        {restoreAction}
      </Section>
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
          title={t("versions.preview.loadError.title")}
          description={
            fetchErrorDetail(error) ??
            t("versions.preview.loadError.description")
          }
        />
      )}
      {preview && !isLoading && !error && (
        <>
          <Content
            font="main-ui-action"
            title={t("versions.versionLabel", {
              number: preview.version_number,
            })}
            description={preview.description}
          />
          <SkillInstructionsPanel
            instructionsMarkdown={
              preview.instructions_markdown ||
              t("preview.noInstructions.message")
            }
          />
        </>
      )}
    </Section>
  );
}
