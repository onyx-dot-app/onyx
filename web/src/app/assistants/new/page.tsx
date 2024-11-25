import CardSection from "@/components/admin/CardSection";
import { HeaderWrapper } from "@/components/header/HeaderWrapper";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { SuccessfulPersonaUpdateRedirectType } from "@/app/admin/assistants/enums";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { LargeBackButton } from "../LargeBackButton";

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
      <div className="w-full my-16">
        <div className="px-32">
          <div className="mx-auto container">
            <CardSection>
              <AssistantEditor
                {...values}
                defaultPublic={false}
                redirectType={SuccessfulPersonaUpdateRedirectType.CHAT}
                shouldAddAssistantToUserPreferences={true}
              />
            </CardSection>
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
              New Assistant
            </h1>
          </div>
        </div>
      </HeaderWrapper>

      {body}
    </div>
  );
}
