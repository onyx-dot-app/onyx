import { ErrorCallout } from "@/components/ErrorCallout";
import { Card, Text, Title } from "@tremor/react";
import { ToolEditor } from "@/app/admin/tools/ToolEditor";
import { fetchToolByIdSS } from "@/lib/tools/fetchTools";
import { DeleteToolButton } from "./DeleteToolButton";
import { FiTool } from "react-icons/fi";
import { AdminPageTitle } from "@/components/admin/Title";
import { BackButton } from "@/components/BackButton";

export default async function Page({ params }: { params: { toolId: string } }) {
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
            <Card>
              <ToolEditor tool={tool} />
            </Card>

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
        icon={<FiTool size={32} className="my-auto" />}
      />

      {body}
    </div>
  );
}
