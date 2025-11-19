import { ErrorCallout } from "@/components/ErrorCallout";
import CardSection from "@/components/admin/CardSection";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { ProjectsProvider } from "@/app/chat/projects/ProjectsContext";

export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const [values, error] = await fetchAssistantEditorInfoSS(params.id);

  if (!values) {
    return (
      <div className="px-32">
        <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
      </div>
    );
  } else {
    return (
      <ProjectsProvider>
        <div className="w-full py-8">
          <div className="px-32">
            <div className="mx-auto container">
              <CardSection className="!border-none !bg-transparent !ring-none">
                <AssistantEditor {...values} defaultPublic={false} />
              </CardSection>
            </div>
          </div>
        </div>
      </ProjectsProvider>
    );
  }
}
