"use client";

import { useEffect, useRef, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import {
  Badge,
  Button,
  MessageCard,
  Modal,
  OnyxLoader,
  Text,
} from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgGitHub } from "@opal/logos";
import { SvgArrowLeft, SvgHistory } from "@opal/icons";
import useScreenSize from "@opal/hooks/useScreenSize";
import type { RichStr } from "@opal/types";
import {
  confirmMarketplaceRetirements,
  getMarketplace,
  removeMarketplace,
  replaceMarketplaceLogin,
  requestMarketplaceSync,
  setupMarketplaceWebhook,
} from "@/lib/marketplaces/api";
import type {
  Marketplace,
  MarketplaceDetail,
  RetirementConfirmation,
} from "@/lib/marketplaces/types";
import {
  fetchErrorDetail,
  isAuthStatusError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { deleteUserSkill } from "@/lib/skills/api";
import { useSkillLimitFeedback } from "@/lib/skills/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import GitHubConnection from "@/sections/marketplaces/GitHubConnection";
import SkillVersions from "@/sections/skills/SkillVersions";
import MarketplaceSummary from "@/sections/marketplaces/MarketplaceSummary";

export interface MarketplaceDetailDialogProps {
  marketplaceId: string;
  open: boolean;
  onClose: () => void;
  onChanged?: () => void;
  getCountLabel?: (marketplace: Marketplace) => string | RichStr | null;
  /** Open the existing sharing controls; refresh this source after saving. */
  onConfigureAccess?: (marketplace: Marketplace) => void;
}

type Action =
  | { kind: "overview" | "remove" | "replace" }
  | {
      kind: "deleteSkill" | "history";
      skill: MarketplaceDetail["skills"][number];
    }
  | { kind: "retire"; confirmation: RetirementConfirmation; names: string[] };

type Operation =
  | "sync"
  | "replace"
  | "remove"
  | "retire"
  | "deleteSkill"
  | "webhook";

export default function MarketplaceDetailDialog(
  props: MarketplaceDetailDialogProps
) {
  return props.open ? (
    <DetailSession key={props.marketplaceId} {...props} />
  ) : null;
}

function DetailSession({
  marketplaceId,
  onClose,
  onChanged,
  onConfigureAccess,
  getCountLabel,
}: MarketplaceDetailDialogProps) {
  const t = useTranslations("marketplaces");
  const skillLimit = useSkillLimitFeedback();
  const format = useFormatter();
  const versionsT = useTranslations("skills.versions");
  const { isSmallScreen } = useScreenSize();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  const cache = useSWRConfig();
  const { data, error, mutate } = useSWR(
    SWR_KEYS.marketplace(marketplaceId),
    () => getMarketplace(marketplaceId),
    {
      refreshInterval: (detail) =>
        detail?.marketplace.sync_pending
          ? 3000
          : detail?.marketplace.webhook_enabled
            ? 10000
            : 0,
      refreshWhenHidden: false,
      onErrorRetry: skipRetryOnAuthError,
      errorRetryCount: 2,
    }
  );
  const [action, setAction] = useState<Action>({ kind: "overview" });
  const [pendingOperation, setPendingOperation] = useState<
    Operation | "history" | null
  >(null);
  const pending = pendingOperation !== null;
  const [failure, setFailure] = useState<string | null>(null);
  const [requested, setRequested] = useState(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const row = data?.marketplace;
  const proposal = row?.retirement_proposal;
  const sameProposal =
    action.kind === "retire" &&
    row?.sync_status === "needs_confirmation" &&
    proposal &&
    !proposal.approved &&
    proposal.revision === action.confirmation.revision &&
    proposal.skill_ids.length === action.confirmation.skill_ids.length &&
    proposal.skill_ids.every((id) =>
      action.confirmation.skill_ids.includes(id)
    );
  const canReview =
    row?.sync_status === "needs_confirmation" &&
    !!proposal &&
    !proposal.approved &&
    proposal.skill_ids.length > 0 &&
    proposal.skill_ids.every((id) =>
      data?.skills.some((skill) => skill.id === id)
    );

  function review() {
    if (!proposal || !data || !canReview) return;
    setAction({
      kind: "retire",
      confirmation: {
        revision: proposal.revision,
        skill_ids: [...proposal.skill_ids],
      },
      names: proposal.skill_ids.flatMap((id) =>
        data.skills
          .filter((skill) => skill.id === id)
          .map((skill) => skill.name)
      ),
    });
  }

  async function run(operation: Operation) {
    if (pending || !row || error) return;
    if (
      operation === "retire" &&
      (action.kind !== "retire" || !sameProposal || row.sync_pending)
    )
      return;
    if (
      operation === "deleteSkill" &&
      (action.kind !== "deleteSkill" ||
        !data?.skills.some(
          (skill) => skill.id === action.skill.id && skill.retired_at
        ))
    )
      return;
    setPendingOperation(operation);
    setFailure(null);
    setRequested(false);
    try {
      if (operation === "deleteSkill" && action.kind === "deleteSkill") {
        await deleteUserSkill(action.skill.id);
        await Promise.all([mutate(), cache.mutate(SWR_KEYS.marketplaces)]);
        if (alive.current) {
          setAction({ kind: "overview" });
          onChanged?.();
        }
        return;
      }
      if (operation === "remove") {
        await removeMarketplace(marketplaceId);
        await cache.mutate(SWR_KEYS.marketplaces);
        if (alive.current) {
          onChanged?.();
          onClose();
        }
        return;
      }
      const updated =
        operation === "sync"
          ? await requestMarketplaceSync(marketplaceId)
          : operation === "replace"
            ? await replaceMarketplaceLogin(marketplaceId)
            : operation === "webhook"
              ? await setupMarketplaceWebhook(marketplaceId)
              : action.kind === "retire"
                ? await confirmMarketplaceRetirements({
                    id: marketplaceId,
                    confirmation: action.confirmation,
                  })
                : null;
      if (!updated) return;
      await mutate(
        { ...data, marketplace: updated, skills: data?.skills ?? [] },
        { revalidate: true }
      );
      void cache.mutate(SWR_KEYS.marketplaces);
      if (alive.current) {
        setAction({ kind: "overview" });
        setRequested(operation !== "webhook");
        onChanged?.();
      }
    } catch (caught) {
      if (alive.current) {
        setFailure(
          skillLimit(caught)?.description ??
            fetchErrorDetail(caught) ??
            (caught instanceof Error ? caught.message : t("requestError"))
        );
        // A rejected confirmation must be reviewed again against fresh detail.
        if (operation !== "deleteSkill") setAction({ kind: "overview" });
        await mutate().catch(() => undefined);
      }
    } finally {
      if (alive.current) setPendingOperation(null);
    }
  }

  function close() {
    if (!pending) onClose();
  }

  const scrollingHeader = isSmallScreen && action.kind === "history";
  const header = (
    <Modal.Header
      icon={
        scrollingHeader
          ? undefined
          : action.kind === "history"
            ? SvgHistory
            : SvgGitHub
      }
      title={
        action.kind === "history"
          ? action.skill.name
          : t(
              action.kind === "deleteSkill"
                ? "deleteSkillTitle"
                : action.kind === "remove"
                  ? "removeTitle"
                  : action.kind === "retire"
                    ? "retireTitle"
                    : action.kind === "replace"
                      ? "replaceLogin"
                      : "details"
            )
      }
      padding={scrollingHeader ? 0 : 2}
      reserveCloseSpace={scrollingHeader}
      onClose={pending ? undefined : close}
    >
      {action.kind === "history" && (
        <Section padding={2} height="auto" width="fit">
          <Badge title={t("retiredLabel")} size={5} />
        </Section>
      )}
    </Modal.Header>
  );

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Modal.Content
        width={action.kind === "history" ? "lg" : "md"}
        height={action.kind === "history" ? "lg" : "fit"}
        maxHeight="85dvh"
        restoreOpeningFocus
      >
        {!scrollingHeader && header}
        <Modal.Body padding={scrollingHeader ? 2 : 4}>
          {scrollingHeader && header}
          <Section height="auto" alignItems="stretch" gap={3}>
            {error ? (
              <>
                <IllustrationContent
                  title={t(
                    isAuthStatusError(error) ? "unauthorized" : "loadError"
                  )}
                  description={fetchErrorDetail(error) ?? undefined}
                />
                <Button onClick={() => void mutate()}>{t("retry")}</Button>
              </>
            ) : !data ? (
              <OnyxLoader />
            ) : (
              <>
                {action.kind !== "history" && (
                  <MarketplaceSummary
                    marketplace={data.marketplace}
                    countLabel={getCountLabel?.(data.marketplace)}
                  />
                )}
                {failure && (
                  <MessageCard
                    variant="error"
                    title={failure}
                    outerPadding={1}
                    innerPadding={1}
                  />
                )}
                {requested && data.marketplace.sync_pending && (
                  <MessageCard
                    variant="queued"
                    title={t("requested")}
                    outerPadding={1}
                    innerPadding={1}
                  />
                )}
                {action.kind === "overview" && (
                  <>
                    {data.marketplace.webhook_available && (
                      <Section height="auto" alignItems="start" gap={2}>
                        <Text font="main-ui-action">
                          {t("pushUpdates.title")}
                        </Text>
                        <Text font="secondary-body">
                          {t(
                            data.marketplace.webhook_enabled
                              ? "pushUpdates.configured"
                              : "pushUpdates.description"
                          )}
                        </Text>
                        {data.marketplace.webhook_enabled && (
                          <>
                            {data.marketplace.webhook_ref && (
                              <Text
                                font="secondary-mono"
                                wordWrap="wrap-anywhere"
                              >
                                {data.marketplace.webhook_ref}
                              </Text>
                            )}
                            <Text font="secondary-body">
                              {data.marketplace.webhook_last_delivery_at
                                ? t("pushUpdates.lastDelivery", {
                                    date: format.dateTime(
                                      new Date(
                                        data.marketplace
                                          .webhook_last_delivery_at
                                      ),
                                      {
                                        dateStyle: "medium",
                                        timeStyle: "short",
                                      }
                                    ),
                                  })
                                : t("pushUpdates.awaitingDelivery")}
                            </Text>
                          </>
                        )}
                        <Button
                          prominence="secondary"
                          disabled={pending}
                          onClick={() => void run("webhook")}
                          aria-label={t(
                            pendingOperation === "webhook"
                              ? "working"
                              : data.marketplace.webhook_enabled
                                ? "pushUpdates.refresh"
                                : "pushUpdates.enable"
                          )}
                        >
                          {t(
                            pendingOperation === "webhook"
                              ? "working"
                              : data.marketplace.webhook_enabled
                                ? "pushUpdates.refreshAction"
                                : "pushUpdates.enableAction"
                          )}
                        </Button>
                      </Section>
                    )}
                    {Object.entries(data.marketplace.blocked_entries).map(
                      ([entry, reason]) => {
                        const limit =
                          data.marketplace.skill_limit_blocks?.[entry];
                        return (
                          <MessageCard
                            key={entry}
                            variant="warning"
                            title={entry}
                            description={
                              limit
                                ? t("skillLimitBlock", {
                                    limit: limit.failed_limit,
                                    count: limit.affected_user_count,
                                  })
                                : reason
                            }
                            outerPadding={1}
                            innerPadding={1}
                          />
                        );
                      }
                    )}
                    {data.skills.map((skill) => (
                      <Section
                        key={skill.id}
                        height="auto"
                        flexDirection="row"
                        justifyContent="between"
                        gap={2}
                      >
                        <Section
                          height="auto"
                          alignItems="start"
                          gap={1}
                          className="min-w-0"
                        >
                          <Text font="secondary-body" wordWrap="wrap-anywhere">
                            {skill.name}
                          </Text>
                          {skill.retired_at && (
                            <Badge title={t("retiredLabel")} size={5} />
                          )}
                        </Section>
                        {skill.retired_at && (
                          <Section
                            flexDirection="row"
                            wrap
                            gap={2}
                            height="auto"
                            width="auto"
                          >
                            <Button
                              prominence="secondary"
                              size="sm"
                              onClick={() =>
                                setAction({ kind: "history", skill })
                              }
                            >
                              {versionsT("title")}
                            </Button>
                            <Button
                              variant="danger"
                              prominence="tertiary"
                              size="sm"
                              disabled={pending}
                              onClick={() => {
                                setFailure(null);
                                setAction({ kind: "deleteSkill", skill });
                              }}
                              aria-label={t("deleteSkill", {
                                name: skill.name,
                              })}
                            >
                              {t("confirmDeleteSkill")}
                            </Button>
                          </Section>
                        )}
                      </Section>
                    ))}
                    {proposal && !proposal.approved && (
                      <Button
                        prominence="secondary"
                        disabled={
                          pending || !canReview || data.marketplace.sync_pending
                        }
                        onClick={review}
                      >
                        {t("reviewRetirements")}
                      </Button>
                    )}
                    {proposal && !proposal.approved && !canReview && (
                      <MessageCard
                        variant="warning"
                        title={t("proposalUnavailable")}
                        outerPadding={1}
                        innerPadding={1}
                      />
                    )}
                    <Section
                      height="auto"
                      flexDirection="row"
                      justifyContent="start"
                      wrap
                      gap={2}
                    >
                      <Button
                        disabled={pending || data.marketplace.sync_pending}
                        onClick={() => void run("sync")}
                      >
                        {t("syncNow")}
                      </Button>
                      <Button
                        prominence="secondary"
                        disabled={pending}
                        onClick={() => setAction({ kind: "replace" })}
                      >
                        {t("replaceLogin")}
                      </Button>
                      {!data.marketplace.owner_user_id &&
                        isGlobalHolder &&
                        onConfigureAccess && (
                          <Button
                            prominence="secondary"
                            disabled={pending}
                            onClick={() => onConfigureAccess(data.marketplace)}
                          >
                            {t("configureAccess")}
                          </Button>
                        )}
                      <Button
                        variant="danger"
                        prominence="tertiary"
                        disabled={pending}
                        onClick={() => setAction({ kind: "remove" })}
                      >
                        {t("remove")}
                      </Button>
                    </Section>
                  </>
                )}
                {action.kind === "history" && (
                  <Section height="auto" alignItems="stretch" gap={2}>
                    <SkillVersions
                      key={action.skill.id}
                      kind="retired"
                      skillId={action.skill.id}
                      onBusyChange={(busy) =>
                        setPendingOperation(busy ? "history" : null)
                      }
                      onRestored={() => onChanged?.()}
                    />
                  </Section>
                )}
                {action.kind === "remove" && (
                  <MessageCard
                    variant="warning"
                    title={t("removeDescription", {
                      name: data.marketplace.name,
                    })}
                    outerPadding={1}
                    innerPadding={1}
                  />
                )}
                {action.kind === "deleteSkill" && (
                  <MessageCard
                    variant="warning"
                    title={t("deleteSkillDescription", {
                      name: action.skill.name,
                    })}
                    outerPadding={1}
                    innerPadding={1}
                  />
                )}
                {action.kind === "replace" && (
                  <>
                    <Text font="main-ui-body">{t("replaceDescription")}</Text>
                    <GitHubConnection />
                  </>
                )}
                {action.kind === "retire" && (
                  <>
                    <Text font="main-ui-body">{t("retireDescription")}</Text>
                    <Text font="secondary-mono" wordWrap="wrap-anywhere">
                      {action.confirmation.revision}
                    </Text>
                    {action.names.map((name, index) => (
                      <Text
                        key={action.confirmation.skill_ids[index]}
                        font="main-ui-action"
                      >
                        {name}
                      </Text>
                    ))}
                    {!sameProposal && (
                      <MessageCard
                        variant="warning"
                        title={t("proposalChanged")}
                        outerPadding={1}
                        innerPadding={1}
                      />
                    )}
                  </>
                )}
              </>
            )}
          </Section>
        </Modal.Body>
        <Modal.Footer padding={scrollingHeader ? 2 : 4} wrap>
          {data && !error && action.kind !== "history" && (
            <Button
              prominence="tertiary"
              disabled={pending}
              onClick={() => void mutate()}
            >
              {t("retry")}
            </Button>
          )}
          {action.kind === "history" ? (
            <Button
              icon={SvgArrowLeft}
              responsiveHideText
              tooltip={t("backToMarketplace")}
              aria-label={t("backToMarketplace")}
              prominence="secondary"
              disabled={pending}
              onClick={() => setAction({ kind: "overview" })}
            >
              {t("backToMarketplace")}
            </Button>
          ) : (
            <Button
              prominence="secondary"
              disabled={pending}
              onClick={
                action.kind === "overview"
                  ? close
                  : () => setAction({ kind: "overview" })
              }
            >
              {t(action.kind === "overview" ? "close" : "cancel")}
            </Button>
          )}
          {action.kind !== "overview" &&
            action.kind !== "history" &&
            !error &&
            data &&
            (action.kind === "retire" && !sameProposal ? (
              <Button disabled={pending || !canReview} onClick={review}>
                {t("reviewRetirements")}
              </Button>
            ) : (
              <Button
                variant={action.kind === "replace" ? "default" : "danger"}
                disabled={
                  pending ||
                  (action.kind === "retire" && data.marketplace.sync_pending) ||
                  (action.kind === "deleteSkill" &&
                    !data.skills.some(
                      (skill) =>
                        skill.id === action.skill.id && skill.retired_at
                    ))
                }
                onClick={() =>
                  void run(
                    action.kind === "deleteSkill"
                      ? "deleteSkill"
                      : action.kind === "remove"
                        ? "remove"
                        : action.kind === "replace"
                          ? "replace"
                          : "retire"
                  )
                }
              >
                {t(
                  pending
                    ? "working"
                    : action.kind === "deleteSkill"
                      ? "confirmDeleteSkill"
                      : action.kind === "remove"
                        ? "confirmRemove"
                        : action.kind === "replace"
                          ? "replaceLogin"
                          : "confirmRetire"
                )}
              </Button>
            ))}
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
