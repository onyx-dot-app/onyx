import { Filters } from "@/lib/searchFilters/types";

export const adminSearch = async (query: string, filters: Filters) => {
  const response = await fetch("/api/admin/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query,
      filters,
    }),
  });
  return response;
};
