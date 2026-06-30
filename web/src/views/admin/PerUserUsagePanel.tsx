"use client";

import { useEffect, useMemo, useState } from "react";
import { toast } from "@/hooks/useToast";
import { PageLoader } from "@/refresh-components/PageLoader";
import { Button, Card, InputTypeIn, MessageCard, Text } from "@opal/components";
import { SvgChevronLeft, SvgChevronRight, SvgX } from "@opal/icons";
import {
  resetUserUsage,
  useUsageExport,
  UsageExportUser,
} from "@/lib/usage/userUsage";

const PAGE_SIZE = 10;

type SortKey =
  | "email"
  | "input_tokens"
  | "output_tokens"
  | "cache_read_tokens"
  | "cost_cents";
type SortDir = "asc" | "desc";

function formatTokens(n: number): string {
  return n.toLocaleString();
}

function formatCost(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

function sortValue(user: UsageExportUser, key: SortKey): number | string {
  if (key === "email") return user.email.toLowerCase();
  return user.totals[key];
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

interface SortHeaderProps {
  label: string;
  sortKey: SortKey;
  activeKey: SortKey;
  dir: SortDir;
  onSort: (key: SortKey) => void;
  align: "left" | "right";
}

// Clickable column header — drives the leaderboard ordering. The active column
// shows a ↑/↓ indicator and a brighter label.
function SortHeader({
  label,
  sortKey,
  activeKey,
  dir,
  onSort,
  align,
}: SortHeaderProps) {
  const active = activeKey === sortKey;
  const indicator = active ? (dir === "desc" ? " ↓" : " ↑") : "";
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSort(sortKey)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSort(sortKey);
        }
      }}
      className={`cursor-pointer select-none ${
        align === "right" ? "w-24 text-right" : "flex-1"
      }`}
    >
      <Text font="main-ui-action" color={active ? "text-05" : "text-03"}>
        {`${label}${indicator}`}
      </Text>
    </div>
  );
}

/**
 * Admin table of per-user token/cost usage for the report window. Search by
 * email and click any column to rank by it (a cost/usage leaderboard); each row
 * has a Reset action that clears the user's current-window usage (lifts a budget
 * block). Filtered + sorted client-side over GET /api/admin/usage/export.
 */
export default function PerUserUsagePanel() {
  const { usage, isLoading, error, refetch } = useUsageExport();
  const [page, setPage] = useState(0);
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("cost_cents");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const users = usage?.users ?? [];

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = q
      ? users.filter((u) => u.email.toLowerCase().includes(q))
      : users;
    return [...filtered].sort((a, b) => {
      const av = sortValue(a, sortKey);
      const bv = sortValue(b, sortKey);
      const cmp =
        typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv)
          : (av as number) - (bv as number);
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [users, query, sortKey, sortDir]);

  const pageCount = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));

  // Jump back to the first page whenever the filter or sort reshapes the list.
  useEffect(() => {
    setPage(0);
  }, [query, sortKey, sortDir]);

  // Clamp the page when the list shrinks (e.g. a reset drops a user off).
  useEffect(() => {
    if (page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      // Numeric columns lead high→low (leaderboard); email reads A→Z.
      setSortDir(key === "email" ? "asc" : "desc");
    }
  }

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

  const pageUsers = visible.slice(page * PAGE_SIZE, page * PAGE_SIZE + PAGE_SIZE);

  return (
    <Card border="solid" rounding="lg" padding="sm">
      <div className="flex flex-col gap-2">
        <Text font="heading-h3">Per-user usage</Text>
        <Text font="secondary-body" color="text-03">
          Tokens (input, output, cache reads) and cost per user over the report
          window. Click a column to rank by it, or search by email. Reset clears
          a user&apos;s current-window usage to lift a budget block; prior
          windows are kept.
        </Text>

        <InputTypeIn
          value={query}
          placeholder="Search users by email…"
          onChange={(e) => setQuery(e.target.value)}
        />

        {users.length === 0 ? (
          <Text font="main-ui-body" color="text-03">
            No usage recorded yet.
          </Text>
        ) : visible.length === 0 ? (
          <Text font="main-ui-body" color="text-03">
            {`No users match "${query}".`}
          </Text>
        ) : (
          <>
            <div className="flex flex-col divide-y divide-border-01">
              <div className="flex flex-row items-center gap-4 py-2">
                <SortHeader
                  label="User"
                  sortKey="email"
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="left"
                />
                <SortHeader
                  label="Input"
                  sortKey="input_tokens"
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortHeader
                  label="Output"
                  sortKey="output_tokens"
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortHeader
                  label="Cache"
                  sortKey="cache_read_tokens"
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
                <SortHeader
                  label="Cost"
                  sortKey="cost_cents"
                  activeKey={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="right"
                />
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
                  {`Page ${page + 1} of ${pageCount} · ${visible.length} users`}
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
