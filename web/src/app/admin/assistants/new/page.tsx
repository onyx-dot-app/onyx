import { AssistantEditor } from "../AssistantEditor";
import { ErrorCallout } from "@/components/ErrorCallout";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { SuccessfulPersonaUpdateRedirectType } from "../enums";

export default async function Page() {
  const [values, error] = await fetchAssistantEditorInfoSS();

  if (!values) {
    return (
      <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
    );
  } else {
    return (
      <div className="w-full">
        <AssistantEditor
          {...values}
          admin
          defaultPublic={true}
          redirectType={SuccessfulPersonaUpdateRedirectType.ADMIN}
        />
      </div>
    );
  }
}
