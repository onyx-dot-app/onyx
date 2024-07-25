import { Tag } from "../types";

export async function getValidTags(
  matchPattern: string | null = null,
  sources: string[] | null = null
): Promise<Tag[]> {
  const params = new URLSearchParams();
  if (matchPattern) params.append("match_pattern", matchPattern);
  if (sources) sources.forEach((source) => params.append("sources", source));

  const response = await fetch(`/api/query/valid-tags?${params.toString()}`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  if (!response.ok) {
    throw new Error("Failed to fetch valid tags");
  }

  return (await response.json()).tags;
}
