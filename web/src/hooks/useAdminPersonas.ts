"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildApiPath } from "@/lib/urlBuilder";
import { Persona } from "@/app/admin/assistants/interfaces";

interface UseAdminPersonasOptions {
  includeDeleted?: boolean;
  getEditable?: boolean;
  includeDefault?: boolean;
  pageNum?: number;
  pageSize?: number;
}

interface PaginatedPersonasResponse {
  items: Persona[];
  total_items: number;
}

export const useAdminPersonas = (options?: UseAdminPersonasOptions) => {
  const {
    includeDeleted = false,
    getEditable = false,
    includeDefault = false,
    pageNum,
    pageSize,
  } = options || {};

  // If pageNum and pageSize are provided, use paginated endpoint.
  const usePagination = pageNum !== undefined && pageSize !== undefined;

  const url = usePagination
    ? buildApiPath("/api/admin/agents", {
        include_deleted: includeDeleted,
        get_editable: getEditable,
        include_default: includeDefault,
        page_num: pageNum,
        page_size: pageSize,
      })
    : buildApiPath("/api/admin/persona", {
        include_deleted: includeDeleted,
        get_editable: getEditable,
      });

  const { data, error, isLoading, mutate } = useSWR<
    Persona[] | PaginatedPersonasResponse
  >(url, errorHandlingFetcher);

  // Handle both paginated and non-paginated responses
  const personas = usePagination
    ? (data as PaginatedPersonasResponse)?.items || []
    : (data as Persona[]) || [];

  const totalItems = usePagination
    ? (data as PaginatedPersonasResponse)?.total_items || 0
    : personas.length;

  return {
    personas,
    totalItems,
    error,
    isLoading,
    refresh: mutate,
  };
};
