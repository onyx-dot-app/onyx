import { ErrorCallout } from "@/components/ErrorCallout";
import CardSection from "@/components/admin/CardSection";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";

export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: { [key: string]: string | string[] | undefined };
}) {
  const resolvedParams = await params;
  const [values, error] = await fetchAssistantEditorInfoSS(resolvedParams.id);

  const isAdmin = searchParams?.admin === "true";

  if (!values) {
    return (
      <div className="px-32">
        <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
      </div>
    );
  } else {
    return (
      <div className="w-full py-8">
        <div className="px-32">
          <div className="mx-auto container">
            <CardSection className="!border-none !bg-transparent !ring-none">
              <AssistantEditor
                {...values}
                defaultPublic={false}
                admin={isAdmin}
              />
            </CardSection>
          </div>
        </div>
      </div>
    );
  }
}
