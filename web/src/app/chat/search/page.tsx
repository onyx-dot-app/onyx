import { SEARCH_PARAMS } from "@/lib/extension/constants";
import WrappedSearch from "./WrappedSearch";

export default async function SearchPage(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const defaultSidebarOff =
    searchParams[SEARCH_PARAMS.DEFAULT_SIDEBAR_OFF] === "true";
  const isTransitioningFromChat =
    searchParams[SEARCH_PARAMS.TRANSITIONING_FROM_CHAT] === "true";

  return (
    <WrappedSearch
      defaultSidebarOff={defaultSidebarOff}
      isTransitioningFromChat={isTransitioningFromChat}
    />
  );
}
