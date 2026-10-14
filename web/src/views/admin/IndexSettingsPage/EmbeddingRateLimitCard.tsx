"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { mutate } from "swr";
import { Button, Card, InputTypeIn, Text } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgRefreshCw } from "@opal/icons";
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

/** A whole number in [1, max], or null. */
function parseWholeNumber(value: string, max: number): number | null {
  if (!/^\d+$/.test(value.trim())) return null;
  const parsed = Number(value);
  return parsed >= 1 && parsed <= max ? parsed : null;
}

interface LimitFieldProps {
  name: string;
  value: string;
  defaultValue: string;
  placeholder: string;
  error: boolean;
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
}

function LimitField({
  name,
  value,
  defaultValue,
  placeholder,
  error,
  onChange,
  onCommit,
}: LimitFieldProps) {
  const t = useTranslations("admin.indexSettings.embeddingRateLimit");

  return (
    <div className="w-48">
      <Hoverable.Root group={name} width="full">
        <InputTypeIn
          inputMode="numeric"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          variant={error ? "error" : undefined}
          rightChildren={
            value !== defaultValue ? (
              <Hoverable.Item group={name} variant="appear-on-hover">
                <Button
                  icon={SvgRefreshCw}
                  tooltip={t("restoreDefault")}
                  prominence="internal"
                  size="sm"
                  onClick={() => onCommit(defaultValue)}
                />
              </Hoverable.Item>
            ) : undefined
          }
          onBlur={() => onCommit(value)}
        />
      </Hoverable.Root>
    </div>
  );
}

/**
 * The global limit on indexing embedding requests. Each field saves on blur
 * and applies to the next embedding batch, without a re-index.
 */
export default function EmbeddingRateLimitCard() {
  const t = useTranslations("admin.indexSettings.embeddingRateLimit");
  const router = useRouter();
  const settings = useSettings();

  const savedRequests = settings.embedding_rate_limit_requests ?? null;
  const savedPeriod =
    settings.embedding_rate_limit_period_seconds ??
    DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS;

  const [requests, setRequests] = useState(
    savedRequests === null ? "" : String(savedRequests)
  );
  const [period, setPeriod] = useState(String(savedPeriod));
  // The values of the last save sent. Saves run one at a time, in order, so
  // the last one sent is the one that sticks.
  const lastSentRef = useRef<{
    requests: number | null;
    period: number;
  } | null>({ requests: savedRequests, period: savedPeriod });
  const saveQueueRef = useRef<Promise<void>>(Promise.resolve());

  // An empty request count means no limit.
  const requestsValid =
    requests.trim() === "" ||
    parseWholeNumber(requests, MAX_EMBEDDING_RATE_LIMIT_REQUESTS) !== null;
  const periodValid =
    parseWholeNumber(period, MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS) !== null;

  function commit(nextRequests: string, nextPeriod: string) {
    setRequests(nextRequests);
    setPeriod(nextPeriod);
    const requestLimit =
      nextRequests.trim() === ""
        ? null
        : parseWholeNumber(nextRequests, MAX_EMBEDDING_RATE_LIMIT_REQUESTS);
    const periodSeconds = parseWholeNumber(
      nextPeriod,
      MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS
    );
    if (
      (nextRequests.trim() !== "" && requestLimit === null) ||
      periodSeconds === null
    ) {
      return;
    }
    const lastSent = lastSentRef.current;
    if (
      lastSent !== null &&
      requestLimit === lastSent.requests &&
      periodSeconds === lastSent.period
    ) {
      return;
    }
    lastSentRef.current = { requests: requestLimit, period: periodSeconds };
    saveQueueRef.current = saveQueueRef.current.then(async () => {
      try {
        await patchSettings({
          embedding_rate_limit_requests: requestLimit,
          embedding_rate_limit_period_seconds: periodSeconds,
        });
        router.refresh();
        await mutate(SWR_KEYS.settings);
        toast.success(t("toasts.saved"));
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
            withLabel
          >
            <LimitField
              name="embedding_rate_limit_requests"
              value={requests}
              defaultValue=""
              placeholder={t("requests.placeholder")}
              error={!requestsValid}
              onChange={setRequests}
              onCommit={(value) => commit(value, period)}
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("period.title")}
            description={t("period.description")}
            suffix={t("period.suffix")}
            withLabel
          >
            <LimitField
              name="embedding_rate_limit_period_seconds"
              value={period}
              defaultValue={String(DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS)}
              placeholder={String(DEFAULT_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS)}
              error={!periodValid}
              onChange={setPeriod}
              onCommit={(value) => commit(requests, value)}
            />
          </InputHorizontal>
          {!requestsValid && (
            <Text font="secondary-body" color="status-error-05">
              {t("validation.requests", {
                max: MAX_EMBEDDING_RATE_LIMIT_REQUESTS,
              })}
            </Text>
          )}
          {!periodValid && (
            <Text font="secondary-body" color="status-error-05">
              {t("validation.period", {
                max: MAX_EMBEDDING_RATE_LIMIT_PERIOD_SECONDS,
              })}
            </Text>
          )}
        </GeneralLayouts.Section>
      </Card>
    </GeneralLayouts.Section>
  );
}
