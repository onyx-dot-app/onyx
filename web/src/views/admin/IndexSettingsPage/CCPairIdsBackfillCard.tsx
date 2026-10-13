"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import { markdown } from "@opal/utils";
import {
  InputSingleSelect,
  MessageCard,
  ProgressBar,
  Text,
} from "@opal/components";
import { toast } from "@opal/layouts";
import { CardLoader } from "@opal/loaders";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useCCPairIdsBackfillStatus } from "@/lib/searchSettings/hooks";
import { updateCCPairAccessMode } from "@/lib/searchSettings/svc";
import type {
  CCPairAccessMode,
  CCPairIdsBackfillStatus,
} from "@/lib/searchSettings/types";

const ACCESS_MODES: CCPairAccessMode[] = ["off", "shadow", "enforce"];

function isAccessMode(value: string): value is CCPairAccessMode {
  return (ACCESS_MODES as string[]).includes(value);
}

interface BackfillStatusProps {
  status: CCPairIdsBackfillStatus;
}

function BackfillDetails({ status }: BackfillStatusProps) {
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
    <div className="flex flex-col gap-2">
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

function AccessModeSelect({ status }: BackfillStatusProps) {
  const t = useTranslations("admin.indexSettings.ccPairIdsBackfill.mode");
  const [saving, setSaving] = useState(false);

  async function handleChange(value: string) {
    if (!isAccessMode(value) || value === status.access_mode || saving) {
      return;
    }
    setSaving(true);
    try {
      const updated = await updateCCPairAccessMode(value);
      await mutate(SWR_KEYS.ccPairIdsBackfillProgress, updated, {
        revalidate: false,
      });
      toast.success(t("toasts.success", { mode: t(`options.${value}.title`) }));
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("toasts.error")
      );
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-row flex-wrap items-center justify-between gap-2">
      <div className="flex flex-col">
        <Text font="main-ui-action" color="text-04">
          {t("label")}
        </Text>
        <Text font="secondary-body" color="text-03">
          {t("description")}
        </Text>
        {status.enforce_requested && !status.completed && (
          <Text font="secondary-body" color="text-03">
            {t("enforcePending")}
          </Text>
        )}
      </div>
      <div className="w-56">
        <InputSingleSelect
          value={status.access_mode}
          onValueChange={handleChange}
          defaultOption={status.access_mode}
          placeholder={t("placeholder")}
          options={ACCESS_MODES.map((mode) => ({
            value: mode,
            title: t(`options.${mode}.title`),
            description: t(`options.${mode}.description`),
            disabled: mode === "enforce" && !status.completed,
            tooltip:
              mode === "enforce" && !status.completed
                ? t("enforceUnavailable")
                : undefined,
          }))}
        />
      </div>
    </div>
  );
}

export default function CCPairIdsBackfillCard() {
  const t = useTranslations("admin.indexSettings.ccPairIdsBackfill");
  const { data: status, isLoading } = useCCPairIdsBackfillStatus();

  if (isLoading) {
    return <CardLoader />;
  }

  // A failed poll keeps the last status, so only a failed first load shows this.
  if (!status) {
    return (
      <MessageCard
        variant="error"
        title={t("loadError.title")}
        description={t("loadError.description")}
      />
    );
  }

  const modeSelect = status.mode_editable ? (
    <AccessModeSelect status={status} />
  ) : null;

  if (status.completed) {
    return (
      <MessageCard
        variant="success"
        title={t("complete.title")}
        description={markdown(t(`complete.description.${status.access_mode}`))}
        bottomChildren={
          modeSelect ? <div className="px-2 py-1">{modeSelect}</div> : undefined
        }
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
        status.started || modeSelect ? (
          <div className="flex flex-col gap-4 px-2 py-1">
            {status.started && <BackfillDetails status={status} />}
            {modeSelect}
          </div>
        ) : undefined
      }
    />
  );
}
