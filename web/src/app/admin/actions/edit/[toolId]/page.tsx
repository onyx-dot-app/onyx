import { ErrorCallout } from "@/components/ErrorCallout";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { ActionEditor } from "@/app/admin/actions/ActionEditor";
import { fetchToolByIdSS } from "@/lib/tools/fetchTools";
import { DeleteToolButton } from "./DeleteToolButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { BackButton } from "@/components/BackButton";
import SvgActions from "@/icons/actions";

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
          errorTitle="Something went wrong :("
          errorMsg="Tool not found"
        />
      </div>
    );
  } else {
    body = (
      <div className="w-full mt-8 pb-8">
        <div>
          <div>
            <CardSection>
              <ActionEditor tool={tool} />
            </CardSection>

            <Title className="mt-12">Delete Action</Title>
            <Text>
              Click the button below to permanently delete this action.
            </Text>
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
        title="Edit Action"
        icon={<SvgActions className="stroke-text-04 h-8 w-8" />}
      />

      {body}
    </div>
  );
}
