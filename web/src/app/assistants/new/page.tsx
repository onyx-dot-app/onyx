import CardSection from "@/components/admin/CardSection";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { ProjectsProvider } from "@/app/chat/projects/ProjectsContext";

export default async function Page() {
  const [values, error] = await fetchAssistantEditorInfoSS();

  let body;
  if (!values) {
    body = (
      <div className="px-32">
        <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
      </div>
    );
  } else {
    body = (
      <div className="w-full py-8">
        <div className="px-32">
          <div className="mx-auto container">
            <CardSection className="!border-none !bg-transparent !ring-none">
              <AssistantEditor
                {...values}
                defaultPublic={false}
                shouldAddAssistantToUserPreferences={true}
              />
            </CardSection>
          </div>
        </div>
      </div>
    );
  }

  return (
    <ProjectsProvider>
      <div>{body}</div>
    </ProjectsProvider>
  );
}
