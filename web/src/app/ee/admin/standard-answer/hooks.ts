import { errorHandlingFetcher } from "@/lib/fetcher";
import { StandardAnswerCategory, StandardAnswer } from "@/lib/types";
import useSWR, { mutate } from "swr";

export const useStandardAnswerCategories = () => {
  const url = "/api/manage/admin/standard-answer/category";
  const swrResponse = useSWR<StandardAnswerCategory[]>(
    url,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshStandardAnswerCategories: () => mutate(url),
  };
};

export const useStandardAnswers = () => {
  const url = "/api/manage/admin/standard-answer";
  const swrResponse = useSWR<StandardAnswer[]>(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshStandardAnswers: () => mutate(url),
  };
};
