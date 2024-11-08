import { ErrorCallout } from "@/components/ErrorCallout";
import { ToolEditor } from "@/app/admin/tools/ToolEditor";
import { fetchToolByIdSS } from "@/lib/tools/fetchTools";
import { AdminPageTitle } from "@/components/admin/Title";
import { BackButton } from "@/components/BackButton";
import { Card, CardContent } from "@/components/ui/card";
import { Wrench } from "lucide-react";
import { DeleteToolButton } from "@/app/admin/tools/edit/[toolId]/DeleteToolButton";

export default async function Page({ params }: { params: { toolId: string, teamspaceId: string } }) {
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
      <div className="w-full">
        <div>
          <div>
            <Card>
              <CardContent>
                <ToolEditor tool={tool} teamspaceId={params.teamspaceId} />
              </CardContent>
            </Card>

            <h3 className="mt-10">Delete Tool</h3>
            <p className="text-sm text-subtle">
              Click the button below to permanently delete this tool.
            </p>
            <div className="flex mt-6">
              <DeleteToolButton toolId={tool.id} teamspaceId={params.teamspaceId} />
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full w-full overflow-y-auto">
      <div className="container">
        <BackButton />

        <AdminPageTitle
          title="Edit Tool"
          icon={<Wrench size={32} className="my-auto" />}
        />

        {body}
      </div>
    </div>
  );
}