"use client";

import { Fragment, useState } from "react";
import useSWR from "swr";

import { Text } from "@opal/components";
import { SvgChevronDown, SvgChevronRight } from "@opal/icons";

import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";
import CardSection from "@/components/admin/CardSection";
import { ThreeDotsLoader } from "@/components/Loading";
import Title from "@/components/ui/title";
import {
  Table,
  TableHeader,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
  TableFooter,
} from "@/components/ui/table";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

interface UsageExportRecord {
  model: string;
  day: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_cents: number;
}

interface UsageExportTotals {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cost_cents: number;
}

interface UsageExportUser {
  email: string;
  totals: UsageExportTotals;
  records: UsageExportRecord[];
}

interface UsageExportResponse {
  start: string;
  end: string;
  users: UsageExportUser[];
}

// Local-time YYYY-MM-DD; the export's start/end are bare dates, not instants,
// so avoid toISOString() which would shift across the UTC boundary.
function toDateParam(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const numberFormatter = new Intl.NumberFormat("en-US");

function formatTokens(value: number): string {
  return numberFormatter.format(value);
}

function formatDollars(cents: number): string {
  return `$${(cents / 100).toFixed(2)}`;
}

interface TokenUsageCostReportProps {
  timeRange: DateRangePickerValue;
}

export function TokenUsageCostReport({ timeRange }: TokenUsageCostReportProps) {
  const [expandedEmail, setExpandedEmail] = useState<string | null>(null);

  // start/end are inclusive bare dates; the endpoint covers the full `end` day.
  const url = SWR_KEYS.adminUsageExport({
    start: timeRange.from ? toDateParam(timeRange.from) : undefined,
    end: timeRange.to ? toDateParam(timeRange.to) : undefined,
  });
  const { data, isLoading, error } = useSWR<UsageExportResponse>(
    url,
    errorHandlingFetcher
  );

  let body;
  if (isLoading) {
    body = (
      <div className="h-40 flex flex-col">
        <ThreeDotsLoader />
      </div>
    );
  } else if (error) {
    body = (
      <div className="text-status-error-05">
        <Text as="p" color="inherit">
          Failed to fetch usage data.
        </Text>
      </div>
    );
  } else if (!data || data.users.length === 0) {
    body = <Text as="p">No usage recorded in this range.</Text>;
  } else {
    const users = [...data.users].sort(
      (a, b) => b.totals.cost_cents - a.totals.cost_cents
    );
    const grandTotals = users.reduce(
      (acc, user) => ({
        input_tokens: acc.input_tokens + user.totals.input_tokens,
        output_tokens: acc.output_tokens + user.totals.output_tokens,
        cache_read_tokens:
          acc.cache_read_tokens + user.totals.cache_read_tokens,
        cost_cents: acc.cost_cents + user.totals.cost_cents,
      }),
      {
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cost_cents: 0,
      }
    );

    body = (
      <Table className="mt-4">
        <TableHeader>
          <TableRow>
            <TableHead>User</TableHead>
            <TableHead className="text-right">Input</TableHead>
            <TableHead className="text-right">Output</TableHead>
            <TableHead className="text-right">Cache</TableHead>
            <TableHead className="text-right">Cost</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.map((user) => {
            const isExpanded = expandedEmail === user.email;
            return (
              <Fragment key={user.email}>
                <TableRow
                  className="cursor-pointer"
                  onClick={() =>
                    setExpandedEmail(isExpanded ? null : user.email)
                  }
                >
                  <TableCell>
                    <div className="flex items-center gap-2">
                      {isExpanded ? (
                        <SvgChevronDown className="w-4 h-4 shrink-0" />
                      ) : (
                        <SvgChevronRight className="w-4 h-4 shrink-0" />
                      )}
                      <Text>{user.email}</Text>
                    </div>
                  </TableCell>
                  <TableCell className="text-right">
                    {formatTokens(user.totals.input_tokens)}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatTokens(user.totals.output_tokens)}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatTokens(user.totals.cache_read_tokens)}
                  </TableCell>
                  <TableCell className="text-right">
                    {formatDollars(user.totals.cost_cents)}
                  </TableCell>
                </TableRow>
                {isExpanded &&
                  user.records.map((record, index) => (
                    <TableRow
                      key={`${user.email}-${record.day}-${record.model}-${index}`}
                      noHover
                      className="bg-background-neutral-01"
                    >
                      <TableCell className="pl-12">
                        <Text color="text-03">{`${record.day} · ${record.model}`}</Text>
                      </TableCell>
                      <TableCell className="text-right">
                        <Text color="text-03">
                          {formatTokens(record.input_tokens)}
                        </Text>
                      </TableCell>
                      <TableCell className="text-right">
                        <Text color="text-03">
                          {formatTokens(record.output_tokens)}
                        </Text>
                      </TableCell>
                      <TableCell className="text-right">
                        <Text color="text-03">
                          {formatTokens(record.cache_read_tokens)}
                        </Text>
                      </TableCell>
                      <TableCell className="text-right">
                        <Text color="text-03">
                          {formatDollars(record.cost_cents)}
                        </Text>
                      </TableCell>
                    </TableRow>
                  ))}
              </Fragment>
            );
          })}
        </TableBody>
        <TableFooter>
          <TableRow noHover>
            <TableCell>
              <Text font="main-ui-action">Total</Text>
            </TableCell>
            <TableCell className="text-right">
              <Text font="main-ui-action">
                {formatTokens(grandTotals.input_tokens)}
              </Text>
            </TableCell>
            <TableCell className="text-right">
              <Text font="main-ui-action">
                {formatTokens(grandTotals.output_tokens)}
              </Text>
            </TableCell>
            <TableCell className="text-right">
              <Text font="main-ui-action">
                {formatTokens(grandTotals.cache_read_tokens)}
              </Text>
            </TableCell>
            <TableCell className="text-right">
              <Text font="main-ui-action">
                {formatDollars(grandTotals.cost_cents)}
              </Text>
            </TableCell>
          </TableRow>
        </TableFooter>
      </Table>
    );
  }

  return (
    <CardSection className="mt-8">
      <Title>Per-User Token Usage &amp; Cost</Title>
      <Text as="p">Token consumption and cost per user over the range</Text>
      {body}
    </CardSection>
  );
}
