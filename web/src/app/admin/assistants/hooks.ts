import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { buildApiPath } from "@/lib/urlBuilder";
import { Persona } from "@/app/admin/assistants/interfaces";

interface UseAdminPersonasOptions {
  includeDeleted?: boolean;
  getEditable?: boolean;
}

export const useAdminPersonas = (options?: UseAdminPersonasOptions) => {
  const { includeDeleted = false, getEditable = false } = options || {};

  const url = buildApiPath("/api/admin/persona", {
    include_deleted: includeDeleted,
    get_editable: getEditable,
  });

  const { data, error, isLoading, mutate } = useSWR<Persona[]>(
    url,
    errorHandlingFetcher
  );

  return {
    personas: data || [],
    error,
    isLoading,
    refresh: mutate,
  };
};
