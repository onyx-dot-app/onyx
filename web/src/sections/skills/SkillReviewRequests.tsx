"use client";

import { useState } from "react";
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
import { SvgCheck, SvgX } from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { reviewSkillVersion } from "@/lib/skills/api";
import type { SkillReviewRequest } from "@/lib/skills/types";
import { useSkillLimitCopy } from "@/lib/skills/limits";

interface SkillReviewRequestsProps {
  /** Called after an approve or a deny changes a skill. */
  onReviewed: () => void;
}

export default function SkillReviewRequests({
  onReviewed,
}: SkillReviewRequestsProps) {
  const t = useTranslations("skills.reviewRequests");
  const { describeError } = useSkillLimitCopy();
  const format = useFormatter();
  const [busyVersionId, setBusyVersionId] = useState<string | null>(null);
  const {
    data: requests,
    error,
    isLoading,
    mutate: refreshRequests,
  } = useSWR<SkillReviewRequest[], Error>(
    SWR_KEYS.skillReviewRequests,
    errorHandlingFetcher
  );

  async function review(
    request: SkillReviewRequest,
    decision: "approve" | "deny"
  ) {
    if (busyVersionId !== null) return;
    const name = request.name ?? t("unnamedSkill");
    setBusyVersionId(request.version_id);
    try {
      await reviewSkillVersion(request.skill_id, request.version_id, decision);
      toast.success(
        decision === "approve"
          ? t("approvedToast", { name, number: request.version_number })
          : t("deniedToast", { name, number: request.version_number })
      );
      onReviewed();
    } catch (err) {
      console.error(`Failed to ${decision} skill publish request`, err);
      toast.error(describeError(err, t("failedToast")));
    } finally {
      setBusyVersionId(null);
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
      weight: 12,
      cell: (versionNumber) => (
        <Text font="main-ui-body" color="text-03">
          {t("versionLabel", { number: versionNumber })}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "published_version_number",
      title: t("columns.kind"),
      weight: 18,
      sortable: false,
      cell: (publishedNumber) =>
        publishedNumber === null ? (
          <Badge title={t("kind.firstPublish")} color="info" />
        ) : (
          <Badge
            title={t("kind.update", { number: publishedNumber })}
            color="default"
          />
        ),
    },
    {
      kind: "data",
      field: "requested_by_email",
      title: t("columns.requestedBy"),
      weight: 24,
      truncate: true,
      cell: (email) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {email ?? t("unknownRequester")}
        </Text>
      ),
    },
    {
      kind: "data",
      field: "requested_at",
      title: t("columns.date"),
      weight: 20,
      cell: (requestedAt) => (
        <Text font="main-ui-body" color="text-03" maxLines={1}>
          {requestedAt
            ? format.dateTime(new Date(requestedAt), {
                dateStyle: "medium",
                timeStyle: "short",
              })
            : ""}
        </Text>
      ),
    },
    {
      kind: "actions",
      showColumnVisibility: false,
      showSorting: false,
      cell: (row) => {
        const name = row.name ?? t("unnamedSkill");
        return (
          <Section flexDirection="row" gap={1} width="auto" height="auto">
            <Button
              size="sm"
              icon={SvgCheck}
              disabled={busyVersionId !== null}
              aria-label={t("approve.ariaLabel", { name })}
              onClick={() => void review(row, "approve")}
            >
              {t("approve.label")}
            </Button>
            <Button
              size="sm"
              prominence="secondary"
              variant="danger"
              icon={SvgX}
              disabled={busyVersionId !== null}
              aria-label={t("deny.ariaLabel", { name })}
              onClick={() => void review(row, "deny")}
            >
              {t("deny.label")}
            </Button>
          </Section>
        );
      },
    },
  ];

  return (
    <Section gap={3} height="auto" alignItems="stretch">
      <Content
        font="main-content-emphasis"
        title={t("title")}
        description={t("description")}
      />
      {isLoading ? (
        <Section height="auto" className="min-h-20">
          <IconLoader />
        </Section>
      ) : error ? (
        <MessageCard
          variant="error"
          title={t("loadError.title")}
          description={t("loadError.description")}
        />
      ) : requests && requests.length > 0 ? (
        <Table
          label={t("title")}
          items={requests}
          columns={columns}
          getRowId={(row) => row.version_id}
          pageSize={false}
          size={2.25}
        />
      ) : (
        <Text font="secondary-body" color="text-03">
          {t("empty")}
        </Text>
      )}
    </Section>
  );
}
