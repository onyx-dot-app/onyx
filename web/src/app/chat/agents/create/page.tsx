import fetchAgentEditorInfoSS from "@/lib/assistants/fetchAgentEditorInfoSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import AgentEditorPage from "@/refresh-pages/AgentEditorPage";

export default async function Page() {
  const [values, error] = await fetchAgentEditorInfoSS();

  if (!values) {
    return (
      <div className="px-32">
        <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
      </div>
    );
  }

  return (
    <AgentEditorPage
      {...values}
      defaultPublic={false}
      shouldAddAssistantToUserPreferences={true}
    />
  );
}
