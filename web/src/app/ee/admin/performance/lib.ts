import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";
import { OnyxBotAnalytics, QueryAnalytics, UserAnalytics } from "./usage/types";
import { useState } from "react";
import { buildApiPath } from "@/lib/urlBuilder";

import {
  convertDateToEndOfDay,
  convertDateToStartOfDay,
  getXDaysAgo,
} from "../../../../components/dateRangeSelectors/dateUtils";
import { THIRTY_DAYS } from "../../../../components/dateRangeSelectors/AdminDateRangeSelector";
import { DateRangePickerValue } from "@/components/dateRangeSelectors/AdminDateRangeSelector";

export const useTimeRange = () => {
  return useState<DateRangePickerValue>({
    to: new Date(),
    from: getXDaysAgo(30),
    selectValue: THIRTY_DAYS,
  });
};

export const useQueryAnalytics = (timeRange: DateRangePickerValue) => {
  const url = buildApiPath("/api/analytics/admin/query", {
    start: convertDateToStartOfDay(timeRange.from)?.toISOString(),
    end: convertDateToEndOfDay(timeRange.to)?.toISOString(),
  });
  const swrResponse = useSWR<QueryAnalytics[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshQueryAnalytics: () => mutate(url),
  };
};

export const useUserAnalytics = (timeRange: DateRangePickerValue) => {
  const url = buildApiPath("/api/analytics/admin/user", {
    start: convertDateToStartOfDay(timeRange.from)?.toISOString(),
    end: convertDateToEndOfDay(timeRange.to)?.toISOString(),
  });
  const swrResponse = useSWR<UserAnalytics[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshUserAnalytics: () => mutate(url),
  };
};

export const useOnyxBotAnalytics = (timeRange: DateRangePickerValue) => {
  const url = buildApiPath("/api/analytics/admin/onyxbot", {
    start: convertDateToStartOfDay(timeRange.from)?.toISOString(),
    end: convertDateToEndOfDay(timeRange.to)?.toISOString(),
  });
  const swrResponse = useSWR<OnyxBotAnalytics[]>(url, errorHandlingFetcher); // TODO

  return {
    ...swrResponse,
    refreshOnyxBotAnalytics: () => mutate(url),
  };
};

// Local calendar day, not the UTC one: toISOString() on a local-midnight Date
// shifts the whole series back a day for users at positive UTC offsets.
function toCalendarDay(date: Date): string {
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

// endDate keeps its default for AgentStats, which charts up to "now".
export function getDatesList(startDate: Date, endDate = new Date()): string[] {
  const datesList: string[] = [];

  for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
    datesList.push(toCalendarDay(d));
  }

  return datesList;
}

export interface PersonaMessageAnalytics {
  total_messages: number;
  date: string;
  persona_id: number;
}

export interface PersonaSnapshot {
  id: number;
  name: string;
  description: string;
  is_listed: boolean;
  is_public: boolean;
}

export const usePersonaMessages = (
  personaId: number | undefined,
  timeRange: DateRangePickerValue
) => {
  const url = buildApiPath(`/api/analytics/admin/persona/messages`, {
    persona_id: personaId?.toString(),
    start: convertDateToStartOfDay(timeRange.from)?.toISOString(),
    end: convertDateToEndOfDay(timeRange.to)?.toISOString(),
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
};

export interface PersonaUniqueUserAnalytics {
  unique_users: number;
  date: string;
  persona_id: number;
}

export const usePersonaUniqueUsers = (
  personaId: number | undefined,
  timeRange: DateRangePickerValue
) => {
  const url = buildApiPath(`/api/analytics/admin/persona/unique-users`, {
    persona_id: personaId?.toString(),
    start: convertDateToStartOfDay(timeRange.from)?.toISOString(),
    end: convertDateToEndOfDay(timeRange.to)?.toISOString(),
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
};
