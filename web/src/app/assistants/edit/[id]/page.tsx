import { ErrorCallout } from "@/components/ErrorCallout";
import Text from "@/components/ui/text";
import CardSection from "@/components/admin/CardSection";
import { HeaderWrapper } from "@/components/header/HeaderWrapper";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { SuccessfulPersonaUpdateRedirectType } from "@/app/admin/assistants/enums";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { DeletePersonaButton } from "@/app/admin/assistants/[id]/DeletePersonaButton";
import { LargeBackButton } from "../../LargeBackButton";
import Title from "@/components/ui/title";

export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
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
            <CardSection>
              <AssistantEditor
                {...values}
                admin
                defaultPublic={false}
                redirectType={SuccessfulPersonaUpdateRedirectType.CHAT}
              />
            </CardSection>
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
