"use client";

import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import { MessageCard, ProgressBar, Text } from "@opal/components";
import { useCCPairIdsBackfillStatus } from "@/lib/searchSettings/hooks";
import type { CCPairIdsBackfillStatus } from "@/lib/searchSettings/types";

interface BackfillDetailsProps {
  status: CCPairIdsBackfillStatus;
}

function BackfillDetails({ status }: BackfillDetailsProps) {
  const t = useTranslations("admin.indexSettings.ccPairIdsBackfill");
  const {
    total_cc_pairs,
    pending_cc_pairs,
    total_documents,
    completed_documents,
    remaining_documents,
    current_cc_pair_name,
  } = status;

  const connectorsLabel =
    total_cc_pairs !== null && pending_cc_pairs !== null
      ? t("status.connectors", {
          done: total_cc_pairs - pending_cc_pairs,
          total: total_cc_pairs,
        })
      : pending_cc_pairs !== null
        ? t("status.connectorsLeft", { count: pending_cc_pairs })
        : null;

  return (
    <div className="flex flex-col gap-2 px-2 py-1">
      {total_documents !== null && completed_documents !== null && (
        <ProgressBar
          value={completed_documents}
          max={total_documents}
          color="blue"
          aria-label={t("progress.ariaLabel")}
        />
      )}
      <div className="flex flex-row flex-wrap items-center justify-between gap-2">
        {connectorsLabel && (
          <Text font="main-ui-body" color="text-03">
            {connectorsLabel}
          </Text>
        )}
        {remaining_documents !== null && (
          <Text font="main-ui-body" color="text-03">
            {t("status.documentsLeft", { count: remaining_documents })}
          </Text>
        )}
      </div>
      {current_cc_pair_name && (
        <Text font="secondary-body" color="text-03">
          {t("status.current", { name: current_cc_pair_name })}
        </Text>
      )}
    </div>
  );
}

export default function CCPairIdsBackfillCard() {
  const t = useTranslations("admin.indexSettings.ccPairIdsBackfill");
  const { data: status } = useCCPairIdsBackfillStatus();

  if (!status) {
    return null;
  }

  if (status.completed) {
    return (
      <MessageCard
        variant="success"
        title={t("complete.title")}
        description={markdown(t(`complete.description.${status.access_mode}`))}
      />
    );
  }

  return (
    <MessageCard
      variant="pending"
      title={t(status.started ? "running.title" : "notStarted.title")}
      description={markdown(
        t(status.started ? "running.description" : "notStarted.description")
      )}
      bottomChildren={
        status.started ? <BackfillDetails status={status} /> : undefined
      }
    />
  );
}
