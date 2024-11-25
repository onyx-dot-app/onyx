import { ErrorCallout } from "@/components/ErrorCallout";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import CardSection from "@/components/admin/CardSection";
import { ToolEditor } from "@/app/admin/tools/ToolEditor";
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
          errorTitle="Something went wrong :("
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
              <ToolEditor tool={tool} />
            </CardSection>

            <Title className="mt-12">Delete Tool</Title>
            <Text>Click the button below to permanently delete this tool.</Text>
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
        title="Edit Tool"
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      {body}
    </div>
  );
}
