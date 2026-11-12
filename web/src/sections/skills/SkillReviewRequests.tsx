"use client";

import { useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { IconLoader } from "@opal/loaders";
import {
  BasicModalFooter,
  Button,
  MessageCard,
  Modal,
  Table,
  Text,
  type TableColumn,
} from "@opal/components";
import { Content, Section, toast } from "@opal/layouts";
import { SvgBlocks, SvgCheck, SvgEye, SvgX } from "@opal/icons";
import { errorHandlingFetcher, fetchErrorDetail } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { reviewSkillVersion } from "@/lib/skills/api";
import type {
  SkillReviewRequest,
  SkillVersionPreview,
} from "@/lib/skills/types";
import { SkillInstructionsPanel } from "@/sections/modals/SkillPreviewModal";

type ReviewDecision = "approve" | "deny";

function useVersionLabel(): (request: SkillReviewRequest) => string {
  const t = useTranslations("skills.reviewRequests");
  return (request) =>
    request.published_version_number === null
      ? t("version.firstPublish", { number: request.version_number })
      : t("version.update", {
          number: request.version_number,
          published: request.published_version_number,
        });
}

interface SkillReviewRequestsProps {
  /** Called after an approve or a deny changes a skill. */
  onReviewed: () => void;
}

export default function SkillReviewRequests({
  onReviewed,
}: SkillReviewRequestsProps) {
  const t = useTranslations("skills.reviewRequests");
  const versionCopy = useTranslations("skills.modals.versions");
  const format = useFormatter();
  const versionLabel = useVersionLabel();
  const [reviewing, setReviewing] = useState<SkillReviewRequest | null>(null);
  const [busy, setBusy] = useState(false);
  const {
    data: requests,
    error,
    isLoading,
    mutate: refreshRequests,
  } = useSWR<SkillReviewRequest[], Error>(
    SWR_KEYS.skillReviewRequests,
    errorHandlingFetcher
  );

  async function review(request: SkillReviewRequest, decision: ReviewDecision) {
    if (busy) return;
    const name = request.name ?? t("unnamedSkill");
    setBusy(true);
    try {
      await reviewSkillVersion(request.skill_id, request.version_id, decision);
      toast.success(
        decision === "approve"
          ? t("approvedToast", { name, number: request.version_number })
          : t("deniedToast", { name, number: request.version_number })
      );
      setReviewing(null);
      onReviewed();
    } catch (err) {
      console.error(`Failed to ${decision} skill publish request`, err);
      toast.error(err instanceof Error ? err.message : t("failedToast"));
    } finally {
      setBusy(false);
      await refreshRequests();
    }
  }

  const columns: TableColumn<SkillReviewRequest>[] = [
    {
      kind: "data",
      field: "name",
      title: t("columns.skill"),
      weight: 26,
      truncate: true,
      cell: (name) => (
        <Text font="main-ui-action" color="text-04" maxLines={1}>
          {name ?? t("unnamedSkill")}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "version_number",
      title: t("columns.version"),
      weight: 26,
      cell: (_versionNumber, row) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {versionLabel(row)}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "author_email",
      title: t("columns.author"),
      weight: 24,
      truncate: true,
      cell: (email) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {email ?? versionCopy("unknownAuthor")}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "version_created_at",
      title: t("columns.saved"),
      weight: 20,
      cell: (savedAt) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {format.dateTime(new Date(savedAt), {
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
      cell: (row) => (
        <Button
          size="sm"
          prominence="secondary"
          icon={SvgEye}
          disabled={busy}
          aria-label={t("review.ariaLabel", {
            name: row.name ?? t("unnamedSkill"),
          })}
          onClick={() => setReviewing(row)}
        >
          {t("review.label")}
        </Button>
      ),
    },
  ];

  if (isLoading || error || !requests || requests.length === 0) return null;

  return (
    <Section gap={3} height="auto" alignItems="stretch">
      <Content
        font="main-content-emphasis"
        title={t("title")}
        description={t("description")}
      />
      <Table
        label={t("title")}
        items={requests}
        columns={columns}
        getRowId={(row) => row.version_id}
        pageSize={false}
        size={2.25}
      />
      {reviewing && (
        <SkillReviewModal
          request={reviewing}
          busy={busy}
          onDecide={(decision) => void review(reviewing, decision)}
          onClose={() => setReviewing(null)}
        />
      )}
    </Section>
  );
}

interface SkillReviewModalProps {
  request: SkillReviewRequest;
  busy: boolean;
  onDecide: (decision: ReviewDecision) => void;
  onClose: () => void;
}

function SkillReviewModal({
  request,
  busy,
  onDecide,
  onClose,
}: SkillReviewModalProps) {
  const t = useTranslations("skills.reviewRequests");
  const versionCopy = useTranslations("skills.modals.versions");
  const modalCopy = useTranslations("skills.modals");
  const versionLabel = useVersionLabel();
  const {
    data: preview,
    error,
    isLoading,
  } = useSWR<SkillVersionPreview, Error>(
    SWR_KEYS.skillVersion(request.skill_id, request.version_id),
    errorHandlingFetcher
  );
  const close = busy ? undefined : onClose;

  return (
    <Modal open onOpenChange={(isOpen) => !isOpen && close?.()}>
      <Modal.Content width="lg" height="lg">
        <Modal.Header
          icon={SvgBlocks}
          title={request.name ?? t("unnamedSkill")}
          description={versionLabel(request)}
          onClose={close}
        />
        <Modal.Body>
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
              title={versionCopy("preview.loadError.title")}
              description={
                fetchErrorDetail(error) ?? versionCopy("loadError.description")
              }
            />
          )}
          {preview && !isLoading && !error && (
            <Section gap={4} height="auto" alignItems="stretch">
              {preview.description && (
                <Text font="main-ui-body" color="text-03">
                  {preview.description}
                </Text>
              )}
              <SkillInstructionsPanel
                instructionsMarkdown={
                  preview.instructions_markdown ||
                  modalCopy("preview.noInstructions.message")
                }
              />
            </Section>
          )}
        </Modal.Body>
        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button
                prominence="secondary"
                variant="danger"
                icon={SvgX}
                disabled={busy}
                onClick={() => onDecide("deny")}
              >
                {t("deny.label")}
              </Button>
            }
            submit={
              <Button
                icon={SvgCheck}
                disabled={busy || !preview}
                onClick={() => onDecide("approve")}
              >
                {t("approve.label")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
