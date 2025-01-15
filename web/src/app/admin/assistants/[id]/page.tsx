import { ErrorCallout } from "@/components/ErrorCallout";
import { AssistantEditor } from "../AssistantEditor";
import { BackButton } from "@/components/BackButton";

import { DeletePersonaButton } from "./DeletePersonaButton";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { SuccessfulPersonaUpdateRedirectType } from "../enums";
import { RobotIcon } from "@/components/icons/icons";
import { AdminPageTitle } from "@/components/admin/Title";
import CardSection from "@/components/admin/CardSection";
import Title from "@/components/ui/title";

export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const [values, error] = await fetchAssistantEditorInfoSS(params.id);

  let body;
  if (!values) {
    body = (
      <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
    );
  } else {
    body = (
      <>
        <CardSection className="!border-none !bg-transparent !ring-none">
          <AssistantEditor
            {...values}
            admin
            defaultPublic={true}
            redirectType={SuccessfulPersonaUpdateRedirectType.ADMIN}
          />
          <Title>Delete Assistant</Title>

          <DeletePersonaButton
            personaId={values.existingPersona!.id}
            redirectType={SuccessfulPersonaUpdateRedirectType.ADMIN}
          />
        </CardSection>
      </>
    );
  }

  return (
    <div className="w-full">
      <AdminPageTitle title="Edit Assistant" icon={<RobotIcon size={32} />} />
      {body}
    </div>
  );
}
