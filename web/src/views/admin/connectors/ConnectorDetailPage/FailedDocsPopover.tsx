"use client";

import type { Route } from "next";
import { Fragment, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Divider,
  InputTypeIn,
  LinkButton,
  Popover,
  ShadowDiv,
  Text,
} from "@opal/components";
import { useDebouncedValue, useOverflow } from "@opal/hooks";
import { Section } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import { LineLoader } from "@opal/loaders";
import { formatDateTimeLog } from "@/lib/dateUtils";
import {
  SvgCheckSquare,
  SvgExternalLink,
  SvgFile,
  SvgRefreshCw,
  SvgUser,
  SvgUsers,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import type { FailedItemsRoute } from "@/lib/ccPair";
import type {
  IndexAttemptError,
  SyncAttemptError,
  SyncEntityKind,
} from "@/lib/connectors/types";
import {
  useLoadMorePages,
  useResolveRunErrors,
} from "@/lib/connectors/ccPair/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { RUNS_POLL_MS } from "@/views/admin/connectors/ConnectorDetailPage/RunsCard";
import { runHref } from "@/views/admin/connectors/ConnectorDetailPage/runLink";
import {
  PLACEMENT_PROPS,
  type PopoverPlacement,
} from "@/views/admin/connectors/ConnectorDetailPage/popoverPlacement";
import {
  SEARCH_DELAY_MS,
  SEARCH_MAX_LENGTH,
} from "@/views/admin/connectors/shared/search";

// The errors and sync-errors routes' largest page.
const PAGE_SIZE = 100;
const CLAMPED_LINES = 5;
// Hidden until the row is hovered or focused. Touch screens always show it.
const ON_ROW_HOVER =
  "opacity-0 no-hover:opacity-100 group-hover/row:opacity-100 group-focus-within/row:opacity-100";

/** What the list holds: an index attempt's failed documents and entities, or a group sync's failed users or groups. */
export type FailedItemsKind = "docs" | "users" | "groups";

interface FailedItemsConfig {
  icon: IconFunctionComponent;
  route: FailedItemsRoute;
  /** Keys under `admin.connector.activity`. */
  title: string;
  search: string;
  empty: string;
}

const KINDS = {
  docs: {
    icon: SvgFile,
    route: "errors",
    title: "docs.title",
    search: "docs.search.placeholder",
    empty: "docs.empty",
  },
  users: {
    icon: SvgUser,
    route: "sync-errors",
    title: "syncErrors.users.title",
    search: "syncErrors.users.search",
    empty: "syncErrors.users.empty",
  },
  groups: {
    icon: SvgUsers,
    route: "sync-errors",
    title: "syncErrors.groups.title",
    search: "syncErrors.groups.search",
    empty: "syncErrors.groups.empty",
  },
} as const satisfies Record<FailedItemsKind, FailedItemsConfig>;

const SYNC_ENTITY_KINDS = {
  users: "user",
  groups: "group",
} satisfies Record<Exclude<FailedItemsKind, "docs">, SyncEntityKind>;

/** What a row reads. An index error is one as it is. A failed user or group has no document, so it never retries. */
type FailedItem = Pick<
  IndexAttemptError,
  | "id"
  | "time_created"
  | "failure_message"
  | "is_resolved"
  | "resolved_reason"
  | "resolved_by_index_attempt_id"
  | "document_id"
  | "document_link"
  | "document_name"
  | "entity_id"
>;

function isSyncError(
  error: IndexAttemptError | SyncAttemptError
): error is SyncAttemptError {
  return "entity_kind" in error;
}

function syncItem(error: SyncAttemptError): FailedItem {
  return {
    id: error.id,
    time_created: error.time_created,
    failure_message: error.failure_message,
    is_resolved: error.is_resolved,
    resolved_reason: error.resolved_reason,
    resolved_by_index_attempt_id: null,
    document_id: null,
    document_link: null,
    document_name: error.entity_name,
    entity_id: error.entity_id,
  };
}

type ErrorGroup = "open" | "withoutRetry" | "closed";

/** Closed by a run, a retry or a legacy resolve; resolved without retry (Retry Doc still takes it); or open. */
function errorGroup(error: FailedItem): ErrorGroup {
  if (error.is_resolved) return "closed";
  return error.resolved_reason === "without_retry" ? "withoutRetry" : "open";
}

function errorKey(error: { id: number }): number {
  return error.id;
}

interface RowIconButtonProps {
  icon: IconFunctionComponent;
  /** The tooltip and the accessible name. */
  label: string;
  onClick?: React.MouseEventHandler<HTMLElement>;
  href?: Route;
  disabled?: boolean;
}

function RowIconButton({ icon, label, ...rest }: RowIconButtonProps) {
  return (
    <Button
      icon={icon}
      prominence="internal"
      size="sm"
      tooltip={label}
      aria-label={label}
      {...rest}
    />
  );
}

interface FailedDocActionsProps {
  ccPairId: number;
  error: FailedItem;
  canRetry: boolean;
  canResolveErrors: boolean;
  busy: boolean;
  onRetry: () => void;
  onResolveWithoutRetry: () => void;
}

/** The row's action column: what the viewer can still do with the error, or how it closed. */
function FailedDocActions({
  ccPairId,
  error,
  canRetry,
  canResolveErrors,
  busy,
  onRetry,
  onResolveWithoutRetry,
}: FailedDocActionsProps) {
  const t = useTranslations("admin.connector.activity");
  const navigation = useNavigation();
  // Only a document can be re-fetched. An entity-level error has nothing to target.
  const canRetryDoc = canRetry && error.document_id !== null;
  const retry = canRetryDoc && (
    <RowIconButton
      icon={SvgRefreshCw}
      label={t("docs.resolveOne")}
      disabled={busy}
      onClick={onRetry}
    />
  );

  switch (errorGroup(error)) {
    case "open":
      return (
        <Section
          width="fit"
          height="fit"
          gap={1}
          padding={0.5}
          className={ON_ROW_HOVER}
        >
          {canResolveErrors && (
            <RowIconButton
              icon={SvgCheckSquare}
              label={
                canRetryDoc
                  ? t("docs.resolveWithoutRetry")
                  : t("actions.resolve")
              }
              disabled={busy}
              onClick={onResolveWithoutRetry}
            />
          )}
          {retry}
        </Section>
      );
    case "withoutRetry":
      return (
        <Section width="fit" height="fit" gap={1} padding={0.5}>
          {/* A button only for its tooltip and accessible name. Retry Doc, on a row with a document, is its one action. */}
          <RowIconButton
            icon={SvgCheckSquare}
            label={
              canRetryDoc ? t("docs.resolvedWithoutRetry") : t("tags.resolved")
            }
          />
          {retry && (
            <Section width="fit" height="fit" className={ON_ROW_HOVER}>
              {retry}
            </Section>
          )}
        </Section>
      );
    case "closed": {
      // The closing run is gone (deleted attempts null it), never recorded on legacy rows, or not sent by an API without provenance.
      const closingRun = error.resolved_by_index_attempt_id ?? null;
      if (closingRun === null) return null;
      return (
        <Section width="fit" height="fit" padding={0.5}>
          <RowIconButton
            icon={SvgExternalLink}
            label={t("docs.resolvedByLaterRun")}
            {...navigation.linkTo(
              runHref(ccPairId, { id: closingRun, kind: "indexing" })
            )}
          />
        </Section>
      );
    }
  }
}

interface FailedDocIdentityProps {
  error: FailedItem;
  icon: IconFunctionComponent;
}

/** "{title} ({id})" on one line: the title truncates first, the id keeps up to 120 px. Only the id when the title is unknown or hidden. */
function FailedDocIdentity({ error, icon: Icon }: FailedDocIdentityProps) {
  const t = useTranslations("admin.connector.activity.docs");
  const id = error.document_id ?? error.entity_id;
  if (id === null) {
    return (
      <Text font="secondary-body" color="text-02">
        {t("unknownDocument")}
      </Text>
    );
  }
  const title = error.document_name;
  // Each part stretches its text to its own width, so the text clips there with the full part on hover.
  return (
    <Section
      flexDirection="row"
      justifyContent="start"
      alignItems="center"
      gap={0.5}
      width="fit"
      height="fit"
      className="min-w-0 max-w-60"
    >
      <Section width="fit" height="fit" padding={0.5}>
        <Icon size={12} className="stroke-text-02" />
      </Section>
      {title !== null && (
        <Section
          alignItems="stretch"
          width="auto"
          height="fit"
          className="min-w-0 shrink"
        >
          <Text
            maxLines={1}
            overflowTooltip
            font="secondary-body"
            color="text-02"
          >
            {title}
          </Text>
        </Section>
      )}
      <Section
        alignItems="stretch"
        width="fit"
        height="fit"
        className="max-w-30"
      >
        {/* The leading space collapses on screen but keeps the copied text whole. */}
        <Text
          maxLines={1}
          overflowTooltip
          font="secondary-body"
          color="text-02"
        >
          {title === null ? id : ` (${id})`}
        </Text>
      </Section>
      {error.document_link !== null && (
        <Button
          icon={SvgExternalLink}
          prominence="internal"
          size="2xs"
          href={error.document_link}
          target="_blank"
          aria-label={t("open")}
          tooltip={t("open")}
        />
      )}
    </Section>
  );
}

/** One failed item, a document, a whole entity, a user or a group: when, which, why, and its actions. */
function FailedDocRow({
  icon,
  ...props
}: FailedDocActionsProps & { icon: IconFunctionComponent }) {
  const { error } = props;
  const t = useTranslations("admin.connector.activity.docs");
  const [expanded, setExpanded] = useState(false);
  const [message, setMessage] = useState<HTMLElement | null>(null);
  const clipped = useOverflow(message);
  const open = errorGroup(error) === "open";
  const tone = open ? "text-04" : "text-02";
  return (
    <Section
      flexDirection="row"
      alignItems="start"
      gap={1}
      padding={1}
      height="fit"
      className="group/row min-h-16 rounded-08 hover:bg-background-tint-02"
    >
      <Section
        alignItems="start"
        gap={0}
        padding={0.5}
        width={15.25}
        height="fit"
        className="shrink-0"
      >
        <Text font="secondary-mono" color={tone}>
          {formatDateTimeLog(error.time_created)}
        </Text>
        <FailedDocIdentity error={error} icon={icon} />
      </Section>
      {/* The toggle follows the clamped text, so "More" sits right after the ellipsis. */}
      <Section
        flexDirection="row"
        justifyContent="start"
        alignItems="end"
        gap={0.5}
        padding={0.5}
        height="fit"
        className="min-w-0 flex-1"
      >
        <Text
          ref={setMessage}
          font="secondary-body"
          color={tone}
          wordWrap="wrap-anywhere"
          maxLines={expanded ? undefined : CLAMPED_LINES}
        >
          {error.failure_message}
        </Text>
        {(expanded || clipped) && (
          <Section width="fit" height="fit">
            <LinkButton
              external={false}
              onClick={() => setExpanded((current) => !current)}
            >
              {expanded ? t("less") : t("more")}
            </LinkButton>
          </Section>
        )}
      </Section>
      <FailedDocActions {...props} />
    </Section>
  );
}

export interface FailedDocsPopoverContentProps {
  ccPairId: number;
  /** The index attempt for `docs`, the group sync for `users` and `groups`. */
  attemptId: number;
  kind: FailedItemsKind;
  /** Whether the viewer may re-fetch single documents of this pair. */
  canResolve: boolean;
  /** Whether Retry All Docs shows: the viewer may retry and the run has open documents, which the loaded rows cannot tell. Default: `canResolve`. */
  canRetryAll?: boolean;
  /** Whether the viewer may resolve errors without retry, which takes the run resolve's permission. Default: `canResolve`. */
  canResolveErrors?: boolean;
  /** Retries these errors by a targeted reindex, or every open error of the attempt when `null`. */
  onResolve: (errorIds: number[] | null) => void;
  /** Closes these errors without a reindex and refreshes the feeds. Default: the list's own resolve. */
  onResolveWithoutRetry?: (
    errorIds: number[],
    route: FailedItemsRoute
  ) => Promise<void>;
  /** A retry or resolve is in flight, so the actions wait for it. */
  resolving: boolean;
}

/** The searchable list. It lives inside the content, so a closed popover fetches nothing. */
function FailedDocsBody({
  ccPairId,
  attemptId,
  kind,
  canResolve,
  canRetryAll = canResolve,
  canResolveErrors = canResolve,
  onResolve,
  onResolveWithoutRetry,
  resolving,
}: FailedDocsPopoverContentProps) {
  const t = useTranslations("admin.connector.activity");
  // Serves a panel rendered without a card, which passes no `onResolveWithoutRetry`.
  const fallback = useResolveRunErrors();
  const { icon, route } = KINDS[kind];
  const resolveWithoutRetry =
    onResolveWithoutRetry ??
    ((errorIds: number[], via: FailedItemsRoute) =>
      fallback.resolveWithoutRetry(ccPairId, errorIds, via));
  const [searchInput, setSearchInput] = useState("");
  const q = useDebouncedValue(searchInput.trim(), SEARCH_DELAY_MS);
  const pages = useLoadMorePages<IndexAttemptError | SyncAttemptError>(
    (pageIndex) =>
      kind === "docs"
        ? SWR_KEYS.ccPairAttemptErrors(ccPairId, {
            indexAttemptId: attemptId,
            q,
            pageNum: pageIndex,
            pageSize: PAGE_SIZE,
          })
        : SWR_KEYS.ccPairSyncErrors(ccPairId, {
            attemptId,
            entityKind: SYNC_ENTITY_KINDS[kind],
            q,
            pageNum: pageIndex,
            pageSize: PAGE_SIZE,
          }),
    errorKey,
    PAGE_SIZE,
    RUNS_POLL_MS
  );
  const items: FailedItem[] = pages.items.map((error) =>
    isSyncError(error) ? syncItem(error) : error
  );
  // Both routes order by state, so the resolved groups start at the first row that is not open.
  const firstResolved = items.findIndex((item) => errorGroup(item) !== "open");
  const busy = resolving || fallback.resolving;

  async function resolveRow(errorId: number) {
    await resolveWithoutRetry([errorId], route);
    await pages.mutate();
  }

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
        gap={1}
        height="fit"
        className="shrink-0"
      >
        <Section height="fit" className="min-w-[10rem] flex-1">
          <InputTypeIn
            icon="search"
            variant="internal"
            placeholder={t(KINDS[kind].search)}
            maxLength={SEARCH_MAX_LENGTH}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
          />
        </Section>
        {/* Retry All Docs takes every open document of the run, not the loaded or searched rows, so only the run's count decides it. */}
        {canRetryAll && (
          <Section width="fit" height="fit" padding={1}>
            <Button
              rightIcon={SvgRefreshCw}
              prominence="internal"
              size="sm"
              disabled={busy}
              onClick={() => onResolve(null)}
            >
              {t("docs.resolveAll")}
            </Button>
          </Section>
        )}
      </Section>
      {pages.failed ? (
        <Section padding={1} height="fit">
          <Text font="secondary-body" color="text-03">
            {t("docs.loadError")}
          </Text>
        </Section>
      ) : pages.first === undefined ? (
        <Section padding={1} height="fit">
          <LineLoader lines={3} />
        </Section>
      ) : items.length === 0 ? (
        <Section padding={1} height="fit">
          <Text font="secondary-body" color="text-03">
            {q !== "" ? t("empty.filtered") : t(KINDS[kind].empty)}
          </Text>
        </Section>
      ) : (
        <ShadowDiv
          variant="mask"
          shadowDirection="bottom-only"
          shadowHeight={8}
          className="max-h-148"
        >
          {items.map((item, index) => (
            <Fragment key={item.id}>
              {index === firstResolved && (
                <Divider title={t("docs.resolvedGroup")} />
              )}
              <FailedDocRow
                ccPairId={ccPairId}
                icon={icon}
                error={item}
                canRetry={canResolve}
                canResolveErrors={canResolveErrors}
                busy={busy}
                onRetry={() => onResolve([item.id])}
                onResolveWithoutRetry={() => void resolveRow(item.id)}
              />
            </Fragment>
          ))}
          {pages.hasMore && (
            <Section alignItems="center" height="fit">
              <Button prominence="tertiary" size="xs" onClick={pages.more}>
                {t("more")}
              </Button>
            </Section>
          )}
        </ShadowDiv>
      )}
    </Section>
  );
}

/** One attempt's errors, open then resolved, under its card: an index attempt's documents and whole entities, or a group sync's users or groups. Radix mounts the content only while open, so nothing is fetched until then. */
export default function FailedDocsPopoverContent({
  placement,
  ...props
}: FailedDocsPopoverContentProps & { placement: PopoverPlacement }) {
  const t = useTranslations("admin.connector.activity");
  return (
    <Popover.Content
      width={160}
      {...PLACEMENT_PROPS[placement]}
      aria-label={t(KINDS[props.kind].title)}
    >
      <FailedDocsBody {...props} />
    </Popover.Content>
  );
}
