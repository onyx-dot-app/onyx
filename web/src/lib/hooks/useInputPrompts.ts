import useSWR from "swr";
import { InputPrompt } from "@/app/chat/interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";

export function useInputPrompts() {
  const { data, error, mutate } = useSWR<InputPrompt[]>(
    "/api/input_prompt?include_public=true",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    inputPrompts: data ?? [],
    isLoading: !error && !data,
    error,
    refresh: mutate,
  };
}
