import { PersonasTable } from "./PersonaTable";
import { FiPlusSquare } from "react-icons/fi";
import Link from "next/link";
import { Divider, Text, Title } from "@tremor/react";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { Persona } from "./interfaces";
import { AssistantsIcon, RobotIcon } from "@/components/icons/icons";
import { AdminPageTitle } from "@/components/admin/Title";

export default async function Page() {
  const allPersonaResponse = await fetchSS("/admin/persona");
  const editablePersonaResponse = await fetchSS(
    "/admin/persona?get_editable=true"
  );

  if (!allPersonaResponse.ok || !editablePersonaResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch personas - ${
          (await allPersonaResponse.text()) ||
          (await editablePersonaResponse.text())
        }`}
      />
    );
  }

  const allPersonas = (await allPersonaResponse.json()) as Persona[];
  const editablePersonas = (await editablePersonaResponse.json()) as Persona[];

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
        <Divider />

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

        <Divider />

        <Title>Existing Assistants</Title>
        <PersonasTable
          allPersonas={allPersonas}
          editablePersonas={editablePersonas}
        />
      </div>
    </div>
  );
}
