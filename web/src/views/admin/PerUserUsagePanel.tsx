"use client";

import { useState } from "react";
import { toast } from "@/hooks/useToast";
import { PageLoader } from "@/refresh-components/PageLoader";
import { Button, Card, MessageCard, Text } from "@opal/components";
import { SvgX } from "@opal/icons";
import {
  resetUserUsage,
  useUsageExport,
  UsageExportUser,
} from "@/lib/usage/userUsage";

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
      <div className="w-28 text-right">
        <Text font="main-ui-body" color="text-03">
          {formatTokens(totals.input_tokens)}
        </Text>
      </div>
      <div className="w-28 text-right">
        <Text font="main-ui-body" color="text-03">
          {formatTokens(totals.output_tokens)}
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

/**
 * Admin table of per-user token/cost usage for the report window, each row with
 * a Reset action that clears the user's current-window usage (lifts a budget
 * block). Backed by GET /api/admin/usage/export.
 */
export default function PerUserUsagePanel() {
  const { usage, isLoading, error, refetch } = useUsageExport();

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

  const users = usage?.users ?? [];

  return (
    <Card border="solid" rounding="lg" padding="sm">
      <div className="flex flex-col gap-2">
        <Text font="heading-h3">Per-user usage</Text>
        <Text font="secondary-body" color="text-03">
          Tokens and cost per user over the report window. Reset clears a user&apos;s
          current-window usage to lift a budget block; prior windows are kept.
        </Text>

        {users.length === 0 ? (
          <Text font="main-ui-body" color="text-03">
            No usage recorded yet.
          </Text>
        ) : (
          <div className="flex flex-col divide-y divide-border-01">
            <div className="flex flex-row items-center gap-4 py-2">
              <div className="flex-1">
                <Text font="main-ui-action">User</Text>
              </div>
              <div className="w-28 text-right">
                <Text font="main-ui-action">Input</Text>
              </div>
              <div className="w-28 text-right">
                <Text font="main-ui-action">Output</Text>
              </div>
              <div className="w-24 text-right">
                <Text font="main-ui-action">Cost</Text>
              </div>
              <div className="w-[68px]" />
            </div>
            {users.map((user) => (
              <UsageRow key={user.email} user={user} onReset={refetch} />
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
