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
  DEFAULT_EMBEDDING_RETRY_BACKOFF_MAX_SECONDS,
  DEFAULT_EMBEDDING_RETRY_BACKOFF_SCALE_SECONDS,
  MAX_EMBEDDING_RETRY_BACKOFF_SECONDS,
} from "@/lib/searchSettings/constants";

type BackoffFieldName =
  | "embedding_retry_backoff_scale_seconds"
  | "embedding_retry_backoff_max_seconds";

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

/** A value is valid when it is a number in (0, MAX]. */
function parseSeconds(value: string): number | null {
  const parsed = Number(value);
  if (
    value.trim() === "" ||
    !Number.isFinite(parsed) ||
    parsed <= 0 ||
    parsed > MAX_EMBEDDING_RETRY_BACKOFF_SECONDS
  ) {
    return null;
  }
  return parsed;
}

interface SecondsFieldProps {
  name: BackoffFieldName;
  value: string;
  defaultValue: number;
  error: boolean;
  onChange: (value: string) => void;
  onCommit: (value: string) => void;
}

function SecondsField({
  name,
  value,
  defaultValue,
  error,
  onChange,
  onCommit,
}: SecondsFieldProps) {
  const t = useTranslations("admin.indexSettings.embeddingRetry");
  const restoringRef = useRef(false);

  return (
    <Hoverable.Root group={name} width="full">
      <InputTypeIn
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={String(defaultValue)}
        variant={error ? "error" : undefined}
        rightChildren={
          value !== String(defaultValue) ? (
            <Hoverable.Item group={name} variant="appear-on-hover">
              <Button
                icon={SvgRefreshCw}
                tooltip={t("restoreDefault")}
                prominence="internal"
                onClick={() => {
                  restoringRef.current = true;
                  onCommit(String(defaultValue));
                }}
              />
            </Hoverable.Item>
          ) : undefined
        }
        onBlur={() => {
          // The restore button blurs the input; it already committed.
          if (restoringRef.current) {
            restoringRef.current = false;
            return;
          }
          onCommit(value);
        }}
      />
    </Hoverable.Root>
  );
}

/**
 * The backoff between retries of embedding calls during indexing. Each field
 * saves on blur and applies to the next embedding batch, without a re-index.
 */
export default function EmbeddingRetryBackoffCard() {
  const t = useTranslations("admin.indexSettings.embeddingRetry");
  const router = useRouter();
  const settings = useSettings();

  const savedScale =
    settings.embedding_retry_backoff_scale_seconds ??
    DEFAULT_EMBEDDING_RETRY_BACKOFF_SCALE_SECONDS;
  const savedMax =
    settings.embedding_retry_backoff_max_seconds ??
    DEFAULT_EMBEDDING_RETRY_BACKOFF_MAX_SECONDS;

  const [scale, setScale] = useState(String(savedScale));
  const [max, setMax] = useState(String(savedMax));
  const savedRef = useRef({ scale: savedScale, max: savedMax });

  const parsedScale = parseSeconds(scale);
  const parsedMax = parseSeconds(max);
  const maxBelowScale =
    parsedScale !== null && parsedMax !== null && parsedMax < parsedScale;
  const errorMessage =
    parsedScale === null || parsedMax === null
      ? t("validation.range", { max: MAX_EMBEDDING_RETRY_BACKOFF_SECONDS })
      : maxBelowScale
        ? t("validation.maxBelowScale")
        : null;

  async function commit(nextScale: string, nextMax: string) {
    setScale(nextScale);
    setMax(nextMax);
    const scaleSeconds = parseSeconds(nextScale);
    const maxSeconds = parseSeconds(nextMax);
    if (
      scaleSeconds === null ||
      maxSeconds === null ||
      maxSeconds < scaleSeconds
    ) {
      return;
    }
    const saved = savedRef.current;
    if (scaleSeconds === saved.scale && maxSeconds === saved.max) {
      return;
    }
    try {
      await patchSettings({
        embedding_retry_backoff_scale_seconds: scaleSeconds,
        embedding_retry_backoff_max_seconds: maxSeconds,
      });
      savedRef.current = { scale: scaleSeconds, max: maxSeconds };
      router.refresh();
      await mutate(SWR_KEYS.settings);
      toast.success(t("toasts.saved"));
    } catch (error) {
      toast.error(
        error instanceof Error && error.message
          ? error.message
          : t("toasts.failed")
      );
    }
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
            title={t("scale.title")}
            description={t("scale.description")}
            suffix={t("suffix")}
            withLabel
          >
            <SecondsField
              name="embedding_retry_backoff_scale_seconds"
              value={scale}
              defaultValue={DEFAULT_EMBEDDING_RETRY_BACKOFF_SCALE_SECONDS}
              error={parsedScale === null || maxBelowScale}
              onChange={setScale}
              onCommit={(value) => void commit(value, max)}
            />
          </InputHorizontal>
          <InputHorizontal
            title={t("max.title")}
            description={t("max.description")}
            suffix={t("suffix")}
            withLabel
          >
            <SecondsField
              name="embedding_retry_backoff_max_seconds"
              value={max}
              defaultValue={DEFAULT_EMBEDDING_RETRY_BACKOFF_MAX_SECONDS}
              error={parsedMax === null || maxBelowScale}
              onChange={setMax}
              onCommit={(value) => void commit(scale, value)}
            />
          </InputHorizontal>
          {errorMessage && (
            <Text font="secondary-body" color="status-error-05">
              {errorMessage}
            </Text>
          )}
        </GeneralLayouts.Section>
      </Card>
    </GeneralLayouts.Section>
  );
}
