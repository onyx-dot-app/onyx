import { InputPrompt } from "@/app/chat/interfaces";
import useSWR from "swr";

const fetcher = (url: string) => fetch(url).then((res) => res.json());

export const useAdminInputPrompts = () => {
  const { data, error, mutate } = useSWR<InputPrompt[]>(
    `/api/admin/input_prompt`,
    fetcher
  );

  return {
    data,
    error,
    isLoading: !error && !data,
    refreshInputPrompts: mutate,
  };
};

export const useInputPrompts = (includePublic: boolean = false) => {
  const { data, error, mutate } = useSWR<InputPrompt[]>(
    `/api/input_prompt${includePublic ? "?include_public=true" : ""}`,
    fetcher
  );

  return {
    data,
    error,
    isLoading: !error && !data,
    refreshInputPrompts: mutate,
  };
};

export const useInputPrompt = (id: number) => {
  const { data, error, mutate } = useSWR<InputPrompt>(
    `/api/input_prompt/${id}`,
    fetcher
  );

  return {
    data,
    error,
    isLoading: !error && !data,
    refreshInputPrompt: mutate,
  };
};
