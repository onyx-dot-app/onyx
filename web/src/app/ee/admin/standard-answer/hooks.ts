import { errorHandlingFetcher } from "@/lib/fetcher";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import useSWR, { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";

export const useStandardAnswerCategories = () => {
  const swrResponse = useSWR<StandardAnswerCategory[]>(
    SWR_KEYS.standardAnswerCategories,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshStandardAnswerCategories: () =>
      mutate(SWR_KEYS.standardAnswerCategories),
  };
};

export const useStandardAnswers = () => {
  const swrResponse = useSWR<StandardAnswer[]>(
    SWR_KEYS.standardAnswers,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshStandardAnswers: () => mutate(SWR_KEYS.standardAnswers),
  };
};
