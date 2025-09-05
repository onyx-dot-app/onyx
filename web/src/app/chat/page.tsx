import { SEARCH_PARAMS } from "@/lib/extension/constants";
import ChatLayout from "./WrappedChat";
import { ProjectsProvider } from "./projects/ProjectsContext";

export default async function Page(props: {
  searchParams: Promise<{ [key: string]: string }>;
}) {
  const searchParams = await props.searchParams;
  const firstMessage = searchParams.firstMessage;
  const defaultSidebarOff =
    searchParams[SEARCH_PARAMS.DEFAULT_SIDEBAR_OFF] === "true";

  return (
    <ProjectsProvider>
      <ChatLayout
        firstMessage={firstMessage}
        defaultSidebarOff={defaultSidebarOff}
      />
    </ProjectsProvider>
  );
}
