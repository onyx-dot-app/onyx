"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { Card, InputNumber } from "@opal/components";
import { Content, InputHorizontal, toast } from "@opal/layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import type { Settings } from "@/lib/settings/types";
import {
  DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
  MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
  MAX_EMBEDDING_RATE_LIMIT_REQUESTS,
} from "@/lib/searchSettings/constants";

async function patchSettings(updates: Partial<Settings>): Promise<void> {
  const response = await fetch("/api/admin/settings", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!response.ok) {
    const detail: unknown = (await response.json()).detail;
    throw new Error(typeof detail === "string" ? detail : undefined);
  }
}

/** Whether a value is within the [1, max] bounds the fields clamp to. */
function inRange(value: number, max: number): boolean {
  return value >= 1 && value <= max;
}

/**
 * The global limit on indexing embedding requests. Each field saves on blur
 * or a stepper or reset click, and applies to the next embedding batch,
 * without a re-index.
 */
export default function EmbeddingRateLimitCard() {
  const t = useTranslations("admin.indexSettings.embeddingRateLimit");
  const router = useRouter();
  const settings = useSettings();

  const savedRequests = settings.embedding_rate_limit_requests ?? null;
  const savedPeriod =
    settings.embedding_rate_limit_period_seconds ??
    DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS;

  // An empty request count means no limit.
  const [requests, setRequests] = useState<number | null>(savedRequests);
  const [period, setPeriod] = useState<number>(savedPeriod);
  // The values of the last save sent. Saves run one at a time, in order, so
  // the last one sent is the one that sticks.
  const lastSentRef = useRef<{
    requests: number | null;
    period: number;
  } | null>({ requests: savedRequests, period: savedPeriod });
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());

  function commit(nextRequests: number | null, nextPeriod: number) {
    setRequests(nextRequests);
    setPeriod(nextPeriod);
    // A stored value outside the bounds is not clamped, so it is not sent.
    if (
      !inRange(nextRequests ?? 1, MAX_EMBEDDING_RATE_LIMIT_REQUESTS) ||
      !inRange(nextPeriod, MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS)
    ) {
      return;
    }
    const lastSent = lastSentRef.current;
    if (
      lastSent !== null &&
      nextRequests === lastSent.requests &&
      nextPeriod === lastSent.period
    ) {
      return;
    }
    lastSentRef.current = { requests: nextRequests, period: nextPeriod };
    saveQueueRef.current = saveQueueRef.current.then(async () => {
      try {
        await patchSettings({
          embedding_rate_limit_requests: nextRequests,
          embedding_rate_limit_period_seconds: nextPeriod,
        });
        router.refresh();
        await mutate(SWR_KEYS.settings);
      } catch (error) {
        // The stored values are unknown now, so the next commit always saves.
        lastSentRef.current = null;
        toast.error(
          error instanceof Error && error.message
            ? error.message
            : t("toasts.failed")
        );
      }
    });
  }

  return (
    <GeneralLayouts.Section
      gap={3}
      height="fit"
      alignItems="stretch"
      justifyContent="start"
    >
      <Content
        title={t("title")}
        description={t("description")}
        sizePreset="main-content"
        variant="section"
      />
      <Card border="solid" rounding={4}>
        <GeneralLayouts.Section width="full" alignItems="stretch">
          <InputHorizontal
            title={t("requests.title")}
            description={t("requests.description")}
            suffix="optional"
            withLabel
            fillInput
          >
            <InputNumber
              value={requests}
              onChange={setRequests}
              onCommit={(value) => commit(value, period)}
              min={1}
              max={MAX_EMBEDDING_RATE_LIMIT_REQUESTS}
              // No unit beside the "No limit" placeholder.
              suffix={requests === null ? undefined : t("requests.suffix")}
              placeholder={t("requests.placeholder")}
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("period.title")}
            description={t("period.description")}
            withLabel
            fillInput
          >
            <InputNumber
              value={period}
              onChange={(value) =>
                setPeriod(value ?? DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS)
              }
              onCommit={(value) =>
                commit(
                  requests,
                  value ?? DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS
                )
              }
              min={1}
              max={MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS}
              defaultValue={DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS}
              showReset
              allowEmpty={false}
              suffix={t("period.suffix")}
              placeholder={String(DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS)}
            />
          </InputHorizontal>
        </GeneralLayouts.Section>
      </Card>
    </GeneralLayouts.Section>
  );
}
