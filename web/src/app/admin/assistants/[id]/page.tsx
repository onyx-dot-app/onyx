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
        <CardSection>
          <AssistantEditor
            {...values}
            admin
            defaultPublic={true}
            redirectType={SuccessfulPersonaUpdateRedirectType.ADMIN}
          />
        </CardSection>

        <div className="mt-12">
          <Title>Delete Assistant</Title>

          <div className="flex mt-6">
            <DeletePersonaButton
              personaId={values.existingPersona!.id}
              redirectType={SuccessfulPersonaUpdateRedirectType.ADMIN}
            />
          </div>
        </div>
      </>
    );
  }

  return (
    <div className="w-full">
      <BackButton />
      <AdminPageTitle title="Edit Assistant" icon={<RobotIcon size={32} />} />
      {body}
    </div>
  );
}
