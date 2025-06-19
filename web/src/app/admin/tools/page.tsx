import { ToolsTable } from "./ToolsTable";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { FiPlusSquare } from "react-icons/fi";
import Link from "next/link";
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
        title="Tools"
      />

      <Text className="mb-2">
        Tools allow assistants to retrieve information or take actions.
      </Text>

      <div>
        <Separator />

        <Title>Create a Tool</Title>
        <CreateButton href="/admin/tools/new" text="New Tool" />

        <Separator />

        <Title>Existing Tools</Title>
        <ToolsTable tools={tools} />
      </div>
    </div>
  );
}
