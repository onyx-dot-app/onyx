import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR, { mutate } from "swr";

const GET_EEA_CONFIG_URL = "/api/eea_config/get_eea_config";

export function usePagesList() {
  const url = GET_EEA_CONFIG_URL;
  const swrResponse = useSWR(url, errorHandlingFetcher);

  return {
    ...swrResponse,
    refreshPagesList: () => mutate(url),
  };
}
