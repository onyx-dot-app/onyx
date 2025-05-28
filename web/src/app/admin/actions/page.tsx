import { ActionsTable } from "./ActionTable";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CreateButton from "@/components/ui/createButton";

export default async function Page() {
  const toolResponse = await fetchSS("/tool");

  if (!toolResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch tools - ${await toolResponse.text()}`}
      />
    );
  }

  const tools = (await toolResponse.json()) as ToolSnapshot[];

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ToolIcon size={32} className="my-auto" />}
        title="Actions"
      />

      <Text className="mb-2">
        Actions allow assistants to retrieve information or take actions.
      </Text>

      <div>
        <Separator />

        <Title>Create an Action</Title>
        <CreateButton href="/admin/actions/new" text="New Action" />

        <Separator />

        <Title>Existing Actions</Title>
        <ActionsTable tools={tools} />
      </div>
    </div>
  );
}
