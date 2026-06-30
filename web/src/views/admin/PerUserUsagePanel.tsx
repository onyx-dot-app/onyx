"use client";

import { useEffect, useState } from "react";
import { toast } from "@/hooks/useToast";
import { PageLoader } from "@/refresh-components/PageLoader";
import { Button, Card, MessageCard, Text } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight, SvgX } from "@opal/icons";
import {
  resetUserUsage,
  useUsageExport,
  UsageExportUser,
} from "@/lib/usage/userUsage";

const PAGE_SIZE = 10;

function formatTokens(n: number): string {
  return n.toLocaleString();
}

function formatCost(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

interface UsageRowProps {
  user: UsageExportUser;
  onReset: () => void;
}

function UsageRow({ user, onReset }: UsageRowProps) {
  const [resetting, setResetting] = useState(false);
  const totals = user.totals;

  async function handleReset() {
    setResetting(true);
    try {
      await resetUserUsage(user.email);
      toast.success(`Reset usage for ${user.email}.`);
      onReset();
    } catch (error) {
      const message = error instanceof Error ? error.message : "unknown error";
      toast.error(`Failed to reset usage: ${message}`);
    } finally {
      setResetting(false);
    }
  }

  return (
    <div
      className="flex flex-row items-center gap-4 py-2"
      data-testid={`usage-row-${user.email}`}
    >
      <div className="flex-1 truncate">
        <Text font="main-ui-body">{user.email}</Text>
      </div>
      <div className="w-24 text-right">
        <Text font="main-ui-body" color="text-03">
          {formatTokens(totals.input_tokens)}
        </Text>
      </div>
      <div className="w-24 text-right">
        <Text font="main-ui-body" color="text-03">
          {formatTokens(totals.output_tokens)}
        </Text>
      </div>
      <div className="w-24 text-right">
        <Text font="main-ui-body" color="text-03">
          {formatTokens(totals.cache_read_tokens)}
        </Text>
      </div>
      <div className="w-24 text-right">
        <Text font="main-ui-body">{formatCost(totals.cost_cents)}</Text>
      </div>
      <Button
        variant="default"
        prominence="tertiary"
        size="sm"
        disabled={resetting}
        onClick={handleReset}
      >
        Reset
      </Button>
    </div>
  );
}

function HeaderCell({ label }: { label: string }) {
  return (
    <div className="w-24 text-right">
      <Text font="main-ui-action">{label}</Text>
    </div>
  );
}

/**
 * Admin table of per-user token/cost usage for the report window, each row with
 * a Reset action that clears the user's current-window usage (lifts a budget
 * block). Paginated client-side over GET /api/admin/usage/export.
 */
export default function PerUserUsagePanel() {
  const { usage, isLoading, error, refetch } = useUsageExport();
  const [page, setPage] = useState(0);

  const users = usage?.users ?? [];
  const pageCount = Math.max(1, Math.ceil(users.length / PAGE_SIZE));

  // Clamp the page when the list shrinks (e.g. a reset drops a user off).
  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

  if (isLoading) return <PageLoader />;
  if (error) {
    return (
      <MessageCard
        variant="error"
        icon={SvgX}
        title="Failed to load per-user usage."
      />
    );
  }

  const pageUsers = users.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <Card border="solid" rounding="lg" padding="sm">
      <div className="flex flex-col gap-2">
        <Text font="heading-h3">Per-user usage</Text>
        <Text font="secondary-body" color="text-03">
          Tokens (input, output, cache reads) and cost per user over the report
          window. Reset clears a user&apos;s current-window usage to lift a budget
          block; prior windows are kept.
        </Text>

        {users.length === 0 ? (
          <Text font="main-ui-body" color="text-03">
            No usage recorded yet.
          </Text>
        ) : (
          <>
            <div className="flex flex-col divide-y divide-border-01">
              <div className="flex flex-row items-center gap-4 py-2">
                <div className="flex-1">
                  <Text font="main-ui-action">User</Text>
                </div>
                <HeaderCell label="Input" />
                <HeaderCell label="Output" />
                <HeaderCell label="Cache" />
                <HeaderCell label="Cost" />
                <div className="w-[68px]" />
              </div>
              {pageUsers.map((user) => (
                <UsageRow key={user.email} user={user} onReset={refetch} />
              ))}
            </div>

            {pageCount > 1 && (
              <div className="flex flex-row items-center justify-end gap-3 pt-2">
                <Button
                  variant="default"
                  prominence="tertiary"
                  size="sm"
                  icon={SvgChevronLeft}
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                />
                <Text font="main-ui-body" color="text-03">
                  {`Page ${page + 1} of ${pageCount}`}
                </Text>
                <Button
                  variant="default"
                  prominence="tertiary"
                  size="sm"
                  icon={SvgChevronRight}
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
                />
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}
