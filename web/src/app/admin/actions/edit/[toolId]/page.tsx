import i18n from "@/i18n/init";
import k from "./../../../../../i18n/keys";
import { ErrorCallout } from "@/components/ErrorCallout";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { ActionEditor } from "@/app/admin/actions/ActionEditor";
import { fetchToolByIdSS } from "@/lib/tools/fetchTools";
import { DeleteToolButton } from "./DeleteToolButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { BackButton } from "@/components/BackButton";
import { ToolIcon } from "@/components/icons/icons";

export default async function Page(props: {
  params: Promise<{ toolId: string }>;
}) {
  const params = await props.params;
  const tool = await fetchToolByIdSS(params.toolId);

  let body;
  if (!tool) {
    body = (
      <div>
        <ErrorCallout
          errorTitle={i18n.t(k.SOMETHING_WENT_WRONG)}
          errorMsg="Tool not found"
        />
      </div>
    );
  } else {
    body = (
      <div className="w-full my-8">
        <div>
          <div>
            <CardSection>
              <ActionEditor tool={tool} />
            </CardSection>

            <Title className="mt-12">{i18n.t(k.DELETE_TOOL)}</Title>
            <Text>{i18n.t(k.CLICK_THE_BUTTON_BELOW_TO_PERM)}</Text>
            <div className="flex mt-6">
              <DeleteToolButton toolId={tool.id} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle
        title={i18n.t(k.EDIT_TOOL)}
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      {body}
    </div>
  );
}
