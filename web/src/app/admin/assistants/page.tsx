import { PersonasTable } from "./PersonaTable";
import { FiPlusSquare } from "react-icons/fi";
import Link from "next/link";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Separator } from "@/components/ui/separator";
import { AssistantsIcon } from "@/components/icons/icons";
import { AdminPageTitle } from "@/components/admin/Title";

export default async function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<AssistantsIcon size={32} />} title="Assistants" />

      <Text className="mb-2">
        Assistants are a way to build custom search/question-answering
        experiences for different use cases.
      </Text>
      <Text className="mt-2">They allow you to customize:</Text>
      <div className="text-sm">
        <ul className="list-disc mt-2 ml-4">
          <li>
            The prompt used by your LLM of choice to respond to the user query
          </li>
          <li>The documents that are used as context</li>
        </ul>
      </div>

      <div>
        <Separator />

        <Title>Create an Assistant</Title>
        <Link
          href="/admin/assistants/new"
          className="flex py-2 px-4 mt-2 border border-border h-fit cursor-pointer hover:bg-hover text-sm w-40"
        >
          <div className="mx-auto flex">
            <FiPlusSquare className="my-auto mr-2" />
            New Assistant
          </div>
        </Link>

        <Separator />

        <Title>Existing Assistants</Title>
        <PersonasTable />
      </div>
    </div>
  );
}
