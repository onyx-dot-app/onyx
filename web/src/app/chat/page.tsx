import { DocumentsProvider } from "./my-documents/DocumentsContext";
import { SEARCH_PARAMS } from "@/lib/extension/constants";
import WrappedChat from "./WrappedChat";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const defaultSidebarOff =
    searchParams[SEARCH_PARAMS.DEFAULT_SIDEBAR_OFF] === "true";

  return (
    <DocumentsProvider>
      <WrappedChat
        firstMessage={firstMessage}
        defaultSidebarOff={defaultSidebarOff}
      />
    </DocumentsProvider>
  );
}
