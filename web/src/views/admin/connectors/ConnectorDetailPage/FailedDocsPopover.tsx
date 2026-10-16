"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import useSWRInfinite from "swr/infinite";
import {
  Button,
  InputTypeIn,
  LinkButton,
  OverflowText,
  Popover,
  ShadowDiv,
  Text,
} from "@opal/components";
import { useDebouncedValue, useOverflow } from "@opal/hooks";
import { Section } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { formatTimestamp } from "@opal/time";
import {
  SvgCheckAll,
  SvgCheckSquare,
  SvgExternalLink,
  SvgFile,
} from "@opal/icons";
import type {
  IndexAttemptError,
  PaginatedIndexAttemptErrors,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  RUNS_POLL_MS,
  SEARCH_DELAY_MS,
} from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";

const PAGE_SIZE = 50;
// The errors route refuses a longer search.
const SEARCH_MAX_LENGTH = 200;
const CLAMPED_LINES = 2;

interface FailedDocRowProps {
  error: IndexAttemptError;
  canResolve: boolean;
  resolving: boolean;
  onResolve: () => void;
}
/** One failed document: when, which, why, and a resolve action. */
function FailedDocRow({
  error,
  canResolve,
  resolving,
  onResolve,
}: FailedDocRowProps) {
  const t = useTranslations("admin.connector.activity.docs");
  const [expanded, setExpanded] = useState(false);
  const [message, setMessage] = useState<HTMLElement | null>(null);
  const clipped = useOverflow(message);
  const id = error.document_id ?? error.entity_id;
  return (
    <Section
      flexDirection="row"
      alignItems="start"
      gap={1}
      padding={1}
      height="fit"
      className="rounded-08 hover:bg-background-tint-01"
    >
      <Section
        alignItems="start"
        gap={0}
        width={14.25}
        height="fit"
        className="shrink-0"
      >
        <Text font="secondary-mono" color="text-03">
          {formatTimestamp(error.time_created)}
        </Text>
        {error.document_name !== null && (
          <OverflowText
            font="secondary-body"
            color="text-03"
            wordWrap="wrap-anywhere"
          >
            {error.document_name}
          </OverflowText>
        )}
        {/* The id stays visible under a title so it can still be copied. */}
        {id !== null ? (
          <Section
            flexDirection="row"
            justifyContent="start"
            alignItems="center"
            gap={0.25}
            height="fit"
            className="min-w-0"
          >
            <SvgFile size={12} className="shrink-0 stroke-text-02" />
            <OverflowText
              font="secondary-mono"
              color="text-02"
              wordWrap="wrap-anywhere"
            >
              {id}
            </OverflowText>
            {error.document_link !== null && (
              <Button
                icon={SvgExternalLink}
                prominence="tertiary"
                size="2xs"
                href={error.document_link}
                target="_blank"
                aria-label={t("open")}
                tooltip={t("open")}
              />
            )}
          </Section>
        ) : (
          error.document_name === null && (
            <Text font="secondary-body" color="text-03">
              {t("unknownDocument")}
            </Text>
          )
        )}
      </Section>
      <Section
        alignItems="start"
        gap={0}
        height="fit"
        className="min-w-0 flex-1"
      >
        <Text
          ref={setMessage}
          font="secondary-body"
          color="text-04"
          wordWrap="wrap-anywhere"
          maxLines={expanded ? undefined : CLAMPED_LINES}
        >
          {error.failure_message}
        </Text>
        {(expanded || clipped) && (
          <LinkButton
            external={false}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? t("less") : t("more")}
          </LinkButton>
        )}
      </Section>
      {/* Only a document can be re-fetched. An entity-level error has nothing to target. */}
      {canResolve && error.document_id !== null && (
        <Button
          icon={SvgCheckSquare}
          prominence="tertiary"
          size="xs"
          tooltip={t("resolveOne")}
          aria-label={t("resolveOne")}
          disabled={resolving}
          onClick={onResolve}
        />
      )}
    </Section>
  );
}

export interface FailedDocsPopoverContentProps {
  ccPairId: number;
  indexAttemptId: number;
  /** Whether the viewer may re-fetch single documents of this pair. */
  canResolve: boolean;
  /** Resolves these errors, or every open error of the attempt when `null`. */
  onResolve: (errorIds: number[] | null) => void;
  /** A resolve is in flight, so the resolve actions wait for it. */
  resolving: boolean;
}

/** The searchable list. It lives inside the content, so a closed popover fetches nothing. */
function FailedDocsBody({
  ccPairId,
  indexAttemptId,
  canResolve,
  onResolve,
  resolving,
}: FailedDocsPopoverContentProps) {
  const t = useTranslations("admin.connector.activity.docs");
  const tActivity = useTranslations("admin.connector.activity");
  const [searchInput, setSearchInput] = useState("");
  const q = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const { data, error, size, setSize } =
    useSWRInfinite<PaginatedIndexAttemptErrors>(
      (pageIndex, previous: PaginatedIndexAttemptErrors | null) => {
        if (previous !== null && previous.items.length < PAGE_SIZE) return null;
        return SWR_KEYS.ccPairAttemptErrors(ccPairId, {
          indexAttemptId,
          q,
          pageNum: pageIndex,
          pageSize: PAGE_SIZE,
        });
      },
      errorHandlingFetcher,
      { refreshInterval: RUNS_POLL_MS, keepPreviousData: true }
    );
  useEffect(() => {
    void setSize(1);
  }, [q, setSize]);
  // Polling shifts the offsets as errors resolve, so a row can land on two pages.
  const items = useMemo(() => {
    const seen = new Set<number>();
    return (data ?? []).flatMap((page) =>
      page.items.filter((item) => {
        if (seen.has(item.id)) return false;
        seen.add(item.id);
        return true;
      })
    );
  }, [data]);
  const first = data?.[0];
  const last = data?.[data.length - 1];
  const hasMore =
    first !== undefined &&
    last !== undefined &&
    items.length < first.total_items &&
    last.items.length === PAGE_SIZE;

  return (
    <Section
      alignItems="stretch"
      gap={1}
      padding={1}
      height="auto"
      className="min-h-0"
    >
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        gap={2}
        height="fit"
        className="shrink-0"
      >
        <Section height="fit" className="min-w-0 flex-1">
          <InputTypeIn
            searchIcon
            variant="internal"
            placeholder={t("search.placeholder")}
            maxLength={SEARCH_MAX_LENGTH}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </Section>
        {/* Resolve All takes every open error, so it hides while a search narrows the list. */}
        {canResolve && q === "" && (
          <Button
            icon={SvgCheckAll}
            prominence="tertiary"
            size="xs"
            disabled={resolving}
            onClick={() => onResolve(null)}
          >
            {t("resolveAll")}
          </Button>
        )}
      </Section>
      {error !== undefined ? (
        <Section padding={1} height="fit">
          <Text font="secondary-body" color="text-03">
            {t("loadError")}
          </Text>
        </Section>
      ) : first === undefined ? (
        <Section padding={1} height="fit">
          <LineLoader lines={3} />
        </Section>
      ) : items.length === 0 ? (
        <Section padding={1} height="fit">
          <Text font="secondary-body" color="text-03">
            {q !== "" ? tActivity("empty.filtered") : t("empty")}
          </Text>
        </Section>
      ) : (
        <ShadowDiv className="max-h-130">
          {items.map((item) => (
            <FailedDocRow
              key={item.id}
              error={item}
              canResolve={canResolve}
              resolving={resolving}
              onResolve={() => onResolve([item.id])}
            />
          ))}
          {hasMore && (
            <Section alignItems="center" height="fit">
              <Button
                prominence="tertiary"
                size="xs"
                onClick={() => void setSize(size + 1)}
              >
                {tActivity("more")}
              </Button>
            </Section>
          )}
        </ShadowDiv>
      )}
    </Section>
  );
}

/** One attempt's open document errors beside its card. Radix mounts the content only while open, so nothing is fetched until then. */
export default function FailedDocsPopoverContent(
  props: FailedDocsPopoverContentProps
) {
  const t = useTranslations("admin.connector.activity.docs");
  return (
    <Popover.Content
      width="3xl"
      side="left"
      align="start"
      aria-label={t("title")}
    >
      <FailedDocsBody {...props} />
    </Popover.Content>
  );
}
