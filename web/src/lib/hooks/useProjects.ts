import useSWR from "swr";
import { Project } from "@/app/chat/projects/projectsService";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useProjects() {
  const { data, error, mutate } = useSWR<Project[]>(
    "/api/user/projects/",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 30000,
    }
  );

  return {
    projects: data ?? [],
    isLoading: !error && !data,
    error,
    refreshProjects: mutate,
  };
}
