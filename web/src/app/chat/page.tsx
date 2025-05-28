import { fetchEEASettings } from "@/lib/eea/fetchEEASettings";
import { DocumentsProvider } from "./my-documents/DocumentsContext";
import { SEARCH_PARAMS } from "@/lib/extension/constants";
import WrappedChat from "./WrappedChat";
import { UserDisclaimerModal } from "@/components/search/UserDisclaimerModal";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const defaultSidebarOff =
    searchParams[SEARCH_PARAMS.DEFAULT_SIDEBAR_OFF] === "true";

  const config = await fetchEEASettings();

  const {
    disclaimerTitle,
    disclaimerText
  } = config;
  
  return (
    <>
      <UserDisclaimerModal disclaimerText={disclaimerText} disclaimerTitle={disclaimerTitle}/>
      <DocumentsProvider>
        <WrappedChat
          firstMessage={firstMessage}
          defaultSidebarOff={defaultSidebarOff}
        />
      </DocumentsProvider>
    </>
  );
}
