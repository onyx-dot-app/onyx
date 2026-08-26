"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { cn, markdown } from "@opal/utils";
import type { IconFunctionComponent } from "@opal/types";
import { Button, MessageCard, ProgressBar, Tag, Text } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgClock,
  SvgExpand,
  SvgLoader,
  SvgPauseCircle,
} from "@opal/icons";
import ReindexErrorsModal from "@/views/admin/IndexSettingsPage/ReindexErrorsModal";
import { useReindexProgress } from "@/lib/indexing/hooks";

interface ReindexProgressBannerProps {
  secondaryModelName?: string;
  onCancel: () => void;
}

const ZERO = {
  total: 0,
  waiting: 0,
  in_progress: 0,
  completed: 0,
  failed: 0,
  paused: 0,
};

// Stable identity so the spinner doesn't remount (and restart at 0°) each poll.
const SpinningLoader: IconFunctionComponent = (props) => (
  <SvgLoader {...props} className={cn(props.className, "animate-spin")} />
);

export default function ReindexProgressBanner({
  secondaryModelName,
  onCancel,
}: ReindexProgressBannerProps) {
  const t = useTranslations("admin.indexSettings");
  const [errorsOpen, setErrorsOpen] = useState(false);
  const { data } = useReindexProgress({ pollIntervalMs: 5000 });
  const { total, waiting, in_progress, completed, failed, paused } =
    data ?? ZERO;

  const description = markdown(
    secondaryModelName
      ? t("progressBanner.description.withModel", {
          model: secondaryModelName,
        })
      : t("progressBanner.description.withoutModel")
  );

  return (
    <>
      {errorsOpen && (
        <ReindexErrorsModal onClose={() => setErrorsOpen(false)} />
      )}

      <MessageCard
        variant="pending"
        title={t("progressBanner.title")}
        description={description}
        bottomChildren={
          <div className="flex flex-row items-center gap-4 px-2 py-1">
            <div className="flex flex-1 flex-col gap-2 min-w-0">
              <div className="flex flex-row items-center justify-between gap-2">
                <Text font="main-ui-body" color="text-03" nowrap>
                  {t("progressBanner.status.label")}
                </Text>
                <div className="flex flex-row items-center gap-1.5">
                  <Tag color="purple" icon={SvgClock} title={String(waiting)} />
                  <Tag
                    color="blue"
                    icon={in_progress > 0 ? SpinningLoader : SvgLoader}
                    title={String(in_progress)}
                  />
                  <Tag
                    color="green"
                    icon={SvgCheckCircle}
                    title={String(completed)}
                  />
                  <Tag
                    color="red"
                    icon={SvgAlertCircle}
                    title={String(failed)}
                  />
                  <Tag
                    color="amber"
                    icon={SvgPauseCircle}
                    title={String(paused)}
                  />
                  {(failed > 0 || paused > 0) && (
                    <Button
                      icon={SvgExpand}
                      variant={failed > 0 ? "danger" : "default"}
                      prominence="tertiary"
                      size="sm"
                      tooltip={t("progressBanner.attentionButton.label")}
                      aria-label={t("progressBanner.attentionButton.label")}
                      onClick={() => setErrorsOpen(true)}
                    />
                  )}
                </div>
              </div>
              {/* SUCCESS only: FAILED isn't settled — the port retries it — so a
                  failed unit stays out of the bar until it succeeds (red tag shows it). */}
              <ProgressBar
                value={completed}
                max={total}
                color="blue"
                aria-label={t("progressBanner.progress.ariaLabel")}
              />
            </div>
            <div className="shrink-0">
              <Button variant="danger" prominence="primary" onClick={onCancel}>
                {t("progressBanner.cancelButton.label")}
              </Button>
            </div>
          </div>
        }
      />
    </>
  );
}
