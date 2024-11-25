import { AssistantEditor } from "../AssistantEditor";
import { ErrorCallout } from "@/components/ErrorCallout";
import { RobotIcon } from "@/components/icons/icons";
import { BackButton } from "@/components/BackButton";
import CardSection from "@/components/admin/CardSection";
import { AdminPageTitle } from "@/components/admin/Title";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { SuccessfulPersonaUpdateRedirectType } from "../enums";

export default async function Page() {
  const [values, error] = await fetchAssistantEditorInfoSS();

  let body;
  if (!values) {
    body = (
      <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
    );
  } else {
    body = (
      <CardSection>
        <AssistantEditor
          {...values}
          admin
          defaultPublic={true}
          redirectType={SuccessfulPersonaUpdateRedirectType.ADMIN}
        />
      </CardSection>
    );
  }

  return (
    <div className="w-full">
      <BackButton />
      <AdminPageTitle
        title="Create a New Assistant"
        icon={<RobotIcon size={32} />}
      />
      {body}
    </div>
  );
}
