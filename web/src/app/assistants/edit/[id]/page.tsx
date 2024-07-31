import { ErrorCallout } from "@/components/ErrorCallout";
import { Card, Text, Title } from "@tremor/react";
import { HeaderWrapper } from "@/components/header/HeaderWrapper";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { SuccessfulPersonaUpdateRedirectType } from "@/app/admin/assistants/enums";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { DeletePersonaButton } from "@/app/admin/assistants/[id]/DeletePersonaButton";
import { LargeBackButton } from "../../LargeBackButton";

export default async function Page({ params }: { params: { id: string } }) {
  const [values, error] = await fetchAssistantEditorInfoSS(params.id);

  let body;
  if (!values) {
    body = (
      <div className="px-32">
        <ErrorCallout errorTitle="Something went wrong :(" errorMsg={error} />
      </div>
    );
  } else {
    body = (
      <div className="w-full my-16">
        <div className="px-32">
          <div className="mx-auto container">
            <Card>
              <AssistantEditor
                {...values}
                defaultPublic={false}
                redirectType={SuccessfulPersonaUpdateRedirectType.CHAT}
              />
            </Card>
            <Title className="mt-12">Delete Assistant</Title>
            <Text>
              Click the button below to permanently delete this assistant.
            </Text>
            <div className="flex mt-6">
              <DeletePersonaButton
                personaId={values.existingPersona!.id}
                redirectType={SuccessfulPersonaUpdateRedirectType.CHAT}
              />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <HeaderWrapper>
        <div className="h-full flex flex-col">
          <div className="flex my-auto">
            <LargeBackButton />
            <h1 className="flex text-xl text-strong font-bold my-auto">
              Edit Assistant
            </h1>
          </div>
        </div>
      </HeaderWrapper>
      {body}
    </div>
  );
}
