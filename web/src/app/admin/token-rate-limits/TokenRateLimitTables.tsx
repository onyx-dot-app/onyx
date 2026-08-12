"use client";

import { deleteTokenRateLimit, updateTokenRateLimit } from "./lib";
import { ContentAction, PageLoader, Section, toast } from "@opal/layouts";
import { TokenRateLimitDisplay } from "./types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { Button, Switch, Text } from "@opal/components";
import { SvgTrash, SvgUsers, SvgWallet } from "@opal/icons";
import { formatCurrencyFromCents, formatTokenCount } from "@/lib/format";

const HOURS_PER_DAY = 24;
const UPDATE_ERROR_MESSAGE = "Failed to update token rate limit";
const DELETE_ERROR_MESSAGE = "Failed to delete token rate limit";

function formatBudget(limit: TokenRateLimitDisplay): string {
  const parts: string[] = [];
  if (limit.cost_budget_cents != null) {
    parts.push(formatCurrencyFromCents(limit.cost_budget_cents));
  }
  if (limit.token_budget != null) {
    parts.push(`${formatTokenCount(limit.token_budget * 1000)} tokens`);
  }
  if (parts.length === 0) return "No budget set";
  return `Up to ${parts.join(" or ")}`;
}

function formatCadence(limit: TokenRateLimitDisplay): string {
  const days = limit.period_hours / HOURS_PER_DAY;
  const period = days === 1 ? "every day" : `every ${days} days`;
  return `Resets ${period} at midnight UTC`;
}

interface LimitRowProps {
  limit: TokenRateLimitDisplay;
  isAdmin: boolean;
  onToggle: (id: number) => void;
  onDelete: (id: number) => void;
}

function LimitRow({ limit, isAdmin, onToggle, onDelete }: LimitRowProps) {
  const limitLabel = `${formatBudget(limit)}, ${formatCadence(limit)}`;

  return (
    <div className="rounded-12 border border-border-01 bg-background-neutral-00">
      <ContentAction
        sizePreset="main-ui"
        variant="section"
        icon={limit.group_name !== undefined ? SvgUsers : SvgWallet}
        title={formatBudget(limit)}
        description={formatCadence(limit)}
        tag={
          limit.group_name !== undefined
            ? { title: limit.group_name }
            : undefined
        }
        padding="md"
        center
        rightChildren={
          <div className="flex items-center gap-2">
            <Switch
              checked={limit.enabled}
              disabled={!isAdmin}
              onCheckedChange={() => onToggle(limit.token_id)}
              aria-label={
                limit.enabled ? `Disable ${limitLabel}` : `Enable ${limitLabel}`
              }
            />
            {isAdmin && (
              <Button
                variant="danger"
                prominence="tertiary"
                icon={SvgTrash}
                size="sm"
                tooltip="Delete limit"
                aria-label={`Delete ${limitLabel}`}
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
        error instanceof Error ? error.message : UPDATE_ERROR_MESSAGE
      );
    }
  };

  const handleDelete = async (id: number) => {
    try {
      await deleteTokenRateLimit(id);
      await mutate(fetchUrl);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : DELETE_ERROR_MESSAGE
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
            No limits yet. Create a spending limit to cap usage.
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
  const { data, isLoading, error } = useSWR<TokenRateLimitDisplay[]>(
    fetchUrl,
    errorHandlingFetcher
  );

  if (isLoading) {
    return <PageLoader />;
  }

  if (!isLoading && error) {
    return <Text as="p">Failed to load token rate limits</Text>;
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
