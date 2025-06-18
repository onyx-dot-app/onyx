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

export function getDatesList(startDate: Date): string[] {
  const datesList: string[] = [];
  const endDate = new Date(); // current date

  for (let d = new Date(startDate); d <= endDate; d.setDate(d.getDate() + 1)) {
    const dateStr = d.toISOString().split("T")[0]; // convert date object to 'YYYY-MM-DD' format
    if (dateStr !== undefined) {
      datesList.push(dateStr);
    }
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
  is_visible: boolean;
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
