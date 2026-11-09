"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import { Button, MessageCard, Modal, OnyxLoader, Text } from "@opal/components";
import { IllustrationContent, Section } from "@opal/layouts";
import { SvgGitHub } from "@opal/logos";
import type { RichStr } from "@opal/types";
import {
  confirmMarketplaceRetirements,
  getMarketplace,
  removeMarketplace,
  replaceMarketplaceLogin,
  requestMarketplaceSync,
} from "@/lib/marketplaces/api";
import type {
  Marketplace,
  RetirementConfirmation,
} from "@/lib/marketplaces/types";
import {
  fetchErrorDetail,
  isAuthStatusError,
  skipRetryOnAuthError,
} from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import GitHubConnection from "@/sections/marketplaces/GitHubConnection";
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
  | { kind: "retire"; confirmation: RetirementConfirmation; names: string[] };

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
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_SKILLS);
  const cache = useSWRConfig();
  const { data, error, mutate } = useSWR(
    SWR_KEYS.marketplace(marketplaceId),
    () => getMarketplace(marketplaceId),
    {
      refreshInterval: (detail) =>
        detail?.marketplace.sync_pending ? 3000 : 0,
      refreshWhenHidden: false,
      onErrorRetry: skipRetryOnAuthError,
      errorRetryCount: 2,
    }
  );
  const [action, setAction] = useState<Action>({ kind: "overview" });
  const [pending, setPending] = useState(false);
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

  async function run(operation: "sync" | "replace" | "remove" | "retire") {
    if (pending || !row || error) return;
    if (
      operation === "retire" &&
      (action.kind !== "retire" || !sameProposal || row.sync_pending)
    )
      return;
    setPending(true);
    setFailure(null);
    setRequested(false);
    try {
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
        setRequested(true);
        onChanged?.();
      }
    } catch (caught) {
      if (alive.current) {
        setFailure(fetchErrorDetail(caught) ?? t("requestError"));
        // A rejected confirmation must be reviewed again against fresh detail.
        setAction({ kind: "overview" });
        await mutate().catch(() => undefined);
      }
    } finally {
      if (alive.current) setPending(false);
    }
  }

  function close() {
    if (!pending) onClose();
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <Modal.Content
        width="md"
        height="fit"
        maxHeight="85dvh"
        restoreOpeningFocus
      >
        <Modal.Header
          icon={SvgGitHub}
          title={t(
            action.kind === "remove"
              ? "removeTitle"
              : action.kind === "retire"
                ? "retireTitle"
                : action.kind === "replace"
                  ? "replaceLogin"
                  : "details"
          )}
          onClose={pending ? undefined : close}
        />
        <Modal.Body>
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
                <MarketplaceSummary
                  marketplace={data.marketplace}
                  countLabel={getCountLabel?.(data.marketplace)}
                />
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
                    {Object.entries(data.marketplace.blocked_entries).map(
                      ([entry, reason]) => (
                        <MessageCard
                          key={entry}
                          variant="warning"
                          title={entry}
                          description={reason}
                          outerPadding={1}
                          innerPadding={1}
                        />
                      )
                    )}
                    {data.skills.map((skill) => (
                      <Text key={skill.id} font="secondary-body">
                        {t(skill.retired_at ? "retiredSkill" : "activeSkill", {
                          name: skill.name,
                        })}
                      </Text>
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
        <Modal.Footer>
          {data && !error && (
            <Button
              prominence="tertiary"
              disabled={pending}
              onClick={() => void mutate()}
            >
              {t("retry")}
            </Button>
          )}
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
          {action.kind !== "overview" &&
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
                  (action.kind === "retire" && data.marketplace.sync_pending)
                }
                onClick={() =>
                  void run(
                    action.kind === "remove"
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
