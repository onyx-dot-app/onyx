"use client";

import { useState } from "react";
import useSWR, { mutate } from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildApiPath } from "@/lib/urlBuilder";
import {
  convertDateToEndOfDay,
  convertDateToStartOfDay,
  formatDateForApiParam,
} from "@/lib/dateUtils";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  OnyxBotAnalytics,
  PersonaMessageAnalytics,
  PersonaUniqueUserAnalytics,
  QueryAnalytics,
  UserAnalytics,
} from "@/lib/usage/interfaces";
import type { SystemUsageResponse } from "@/lib/usage/systemUsage";
import {
  THIRTY_DAYS,
  type DateRange,
  type InputDateRangePickerValue,
  rangeForInclusiveDays,
} from "@opal/components";

export function useTimeRange() {
  return useState<InputDateRangePickerValue>({
    ...rangeForInclusiveDays(30),
    selectValue: THIRTY_DAYS,
  });
}

export function useSystemUsage(range?: DateRange) {
  const url = buildApiPath(SWR_KEYS.adminSystemUsage, {
    start: range?.from ? formatDateForApiParam(range.from) : undefined,
    end: range?.to ? formatDateForApiParam(range.to) : undefined,
  });
  const { data, error, isLoading, mutate } = useSWR<SystemUsageResponse, Error>(
    url,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );

  return { usage: data, isLoading, error, refetch: mutate };
}

function analyticsRange(timeRange: InputDateRangePickerValue) {
  return {
    start: convertDateToStartOfDay(timeRange.from)?.toISOString(),
    end: convertDateToEndOfDay(timeRange.to)?.toISOString(),
  };
}

export function useQueryAnalytics(timeRange: InputDateRangePickerValue) {
  const url = buildApiPath(
    "/api/analytics/admin/query",
    analyticsRange(timeRange)
  );
  const swrResponse = useSWR<QueryAnalytics[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshQueryAnalytics: () => mutate(url),
  };
}

export function useUserAnalytics(timeRange: InputDateRangePickerValue) {
  const url = buildApiPath(
    "/api/analytics/admin/user",
    analyticsRange(timeRange)
  );
  const swrResponse = useSWR<UserAnalytics[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshUserAnalytics: () => mutate(url),
  };
}

export function useOnyxBotAnalytics(timeRange: InputDateRangePickerValue) {
  const url = buildApiPath(
    "/api/analytics/admin/onyxbot",
    analyticsRange(timeRange)
  );
  const swrResponse = useSWR<OnyxBotAnalytics[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshOnyxBotAnalytics: () => mutate(url),
  };
}

export function usePersonaMessages(
  personaId: number | undefined,
  timeRange: InputDateRangePickerValue
) {
  const url = buildApiPath("/api/analytics/admin/persona/messages", {
    persona_id: personaId?.toString(),
    ...analyticsRange(timeRange),
  });

  const { data, error, isLoading } = useSWR<PersonaMessageAnalytics[]>(
    personaId !== undefined ? url : null,
    errorHandlingFetcher
  );

  return {
    data,
    error,
    isLoading,
    refreshPersonaMessages: () => mutate(url),
  };
}

export function usePersonaUniqueUsers(
  personaId: number | undefined,
  timeRange: InputDateRangePickerValue
) {
  const url = buildApiPath("/api/analytics/admin/persona/unique-users", {
    persona_id: personaId?.toString(),
    ...analyticsRange(timeRange),
  });

  const { data, error, isLoading } = useSWR<PersonaUniqueUserAnalytics[]>(
    personaId !== undefined ? url : null,
    errorHandlingFetcher
  );

  return {
    data,
    error,
    isLoading,
    refreshPersonaUniqueUsers: () => mutate(url),
  };
}
