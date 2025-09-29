import { ErrorCallout } from "@/components/ErrorCallout";
import CardSection from "@/components/admin/CardSection";
import { AssistantEditor } from "@/app/admin/assistants/AssistantEditor";
import { SuccessfulPersonaUpdateRedirectType } from "@/app/admin/assistants/enums";
import { fetchAssistantEditorInfoSS } from "@/lib/assistants/fetchPersonaEditorInfoSS";
import { BackButton } from "@/components/BackButton";
import i18n from "@/i18n/init-server";
import k from "@/i18n/keys";

export default async function Page(props: { params: Promise<{ id: string }> }) {
  const params = await props.params;
  const [values, error] = await fetchAssistantEditorInfoSS(params.id);

  if (!values) {
    return (
      <div className="px-32">
        <ErrorCallout
          errorTitle={i18n.t(k.SOMETHING_WENT_WRONG)}
          errorMsg={error}
        />
      </div>
    );
  } else {
    return (
      <div className="w-full py-8">
        <div className="px-32">
          <div className="mx-auto container">
            <CardSection className="!border-none !bg-transparent !ring-none">
              <AssistantEditor {...values} defaultPublic={false} />
            </CardSection>
          </div>
        </div>
      </div>
    );
  }
}
