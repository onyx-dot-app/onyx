"use client";

import { useLocale, useTranslations } from "next-intl";
import { deleteTokenRateLimit, updateTokenRateLimit } from "./lib";
import { ContentAction, PageLoader, Section, toast } from "@opal/layouts";
import { TokenRateLimitDisplay } from "./types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { Button, Switch, Text } from "@opal/components";
import { SvgTrash, SvgUsers, SvgWallet } from "@opal/icons";
import { formatCurrencyFromCents, formatTokenCount } from "@/lib/format";

const HOURS_PER_DAY = 24;

interface LimitRowProps {
  limit: TokenRateLimitDisplay;
  isAdmin: boolean;
  onToggle: (id: number) => void;
  onDelete: (id: number) => void;
}

function LimitRow({ limit, isAdmin, onToggle, onDelete }: LimitRowProps) {
  const t = useTranslations("admin.tokenRateLimits");
  const locale = useLocale();

  const cost =
    limit.cost_budget_cents != null
      ? formatCurrencyFromCents(limit.cost_budget_cents, locale)
      : null;
  const tokens =
    limit.token_budget != null
      ? formatTokenCount(limit.token_budget * 1000, locale)
      : null;

  const budget =
    cost !== null && tokens !== null
      ? t("limits.budget.both", { cost, tokens })
      : cost !== null
        ? t("limits.budget.cost", { cost })
        : tokens !== null
          ? t("limits.budget.tokens", { tokens })
          : t("limits.budget.none");
  const cadence = t("limits.cadence.label", {
    days: limit.period_hours / HOURS_PER_DAY,
  });
  const limitLabel = t("limits.row.label", { budget, cadence });

  return (
    <div className="rounded-12 border border-border-01 bg-background-neutral-00">
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={limit.group_name !== undefined ? SvgUsers : SvgWallet}
        title={budget}
        description={cadence}
        tag={
          limit.group_name !== undefined
            ? { title: limit.group_name }
            : undefined
        }
        padding={1}
        center
        rightChildren={
          <div className="flex items-center gap-2">
            <Switch
              checked={limit.enabled}
              disabled={!isAdmin}
              onCheckedChange={() => onToggle(limit.token_id)}
              aria-label={
                limit.enabled
                  ? t("limits.row.disable.ariaLabel", { label: limitLabel })
                  : t("limits.row.enable.ariaLabel", { label: limitLabel })
              }
            />
            {isAdmin && (
              <Button
                variant="danger"
                prominence="tertiary"
                icon={SvgTrash}
                size="sm"
                tooltip={t("limits.row.delete.tooltip")}
                aria-label={t("limits.row.delete.ariaLabel", {
                  label: limitLabel,
                })}
                onClick={() => onDelete(limit.token_id)}
              />
            )}
          </div>
        }
      />
    </div>
  );
}

type TokenRateLimitTableArgs = {
  tokenRateLimits: TokenRateLimitDisplay[];
  description?: string;
  fetchUrl: string;
  hideHeading?: boolean;
  isAdmin: boolean;
};

export const TokenRateLimitTable = ({
  tokenRateLimits,
  description,
  fetchUrl,
  hideHeading,
  isAdmin,
}: TokenRateLimitTableArgs) => {
  const t = useTranslations("admin.tokenRateLimits");

  const handleEnabledChange = async (id: number) => {
    const tokenRateLimit = tokenRateLimits.find(
      (tokenRateLimit) => tokenRateLimit.token_id === id
    );

    if (!tokenRateLimit) {
      return;
    }

    try {
      await updateTokenRateLimit(id, {
        token_budget: tokenRateLimit.token_budget,
        period_hours: tokenRateLimit.period_hours,
        cost_budget_cents: tokenRateLimit.cost_budget_cents,
        enabled: !tokenRateLimit.enabled,
      });
      await mutate(fetchUrl);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("limits.updateFailed.error")
      );
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteTokenRateLimit(id);
      await mutate(fetchUrl);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("limits.deleteFailed.error")
      );
    }
  };

  return (
    <Section alignItems="stretch" height="auto" gap={2}>
      {!hideHeading && description && (
        <Text font="secondary-body" color="text-03" as="p">
          {description}
        </Text>
      )}
      {tokenRateLimits.length === 0 ? (
        <div className="rounded-12 border border-dashed border-border-02 p-4">
          <Text font="secondary-body" color="text-03" as="p">
            {t("limits.empty.message")}
          </Text>
        </div>
      ) : (
        tokenRateLimits.map((tokenRateLimit) => (
          <LimitRow
            key={tokenRateLimit.token_id}
            limit={tokenRateLimit}
            isAdmin={isAdmin}
            onToggle={handleEnabledChange}
            onDelete={handleDelete}
          />
        ))
      )}
    </Section>
  );
};

export const GenericTokenRateLimitTable = ({
  fetchUrl,
  description,
  hideHeading,
  responseMapper,
  isAdmin = true,
}: {
  fetchUrl: string;
  description?: string;
  hideHeading?: boolean;
  responseMapper?: (data: any) => TokenRateLimitDisplay[];
  isAdmin?: boolean;
}) => {
  const t = useTranslations("admin.tokenRateLimits");
  const { data, isLoading, error } = useSWR<TokenRateLimitDisplay[]>(
    fetchUrl,
    errorHandlingFetcher
  );

  if (isLoading) {
    return <PageLoader />;
  }

  if (!isLoading && error) {
    return <Text as="p">{t("limits.loadFailed.error")}</Text>;
  }

  let processedData = data;
  if (responseMapper) {
    processedData = responseMapper(data);
  }

  return (
    <TokenRateLimitTable
      tokenRateLimits={processedData ?? []}
      fetchUrl={fetchUrl}
      description={description}
      hideHeading={hideHeading}
      isAdmin={isAdmin}
    />
  );
};
