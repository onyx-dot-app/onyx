"use client";

import { PersonasTable } from "./PersonaTable";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Separator } from "@/components/ui/separator";
import { AssistantsIcon } from "@/components/icons/icons";
import { AdminPageTitle } from "@/components/admin/Title";
import { SubLabel } from "@/components/Field";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { useAdminPersonas } from "./hooks";
import { Persona } from "./interfaces";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";

function MainContent({
  personas,
  refreshPersonas,
}: {
  personas: Persona[];
  refreshPersonas: () => void;
}) {
  // Filter out default/unified assistants
  const customPersonas = personas.filter((persona) => !persona.builtin_persona);

  return (
    <div>
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
        <CreateButton href="/assistants/new?admin=true">
          New Assistant
        </CreateButton>

        <Separator />

        <Title>Existing Assistants</Title>
        {customPersonas.length > 0 ? (
          <>
            <SubLabel>
              Assistants will be displayed as options on the Chat / Search
              interfaces in the order they are displayed below. Assistants
              marked as hidden will not be displayed. Editable assistants are
              shown at the top.
            </SubLabel>
            <PersonasTable
              personas={customPersonas}
              refreshPersonas={refreshPersonas}
            />
          </>
        ) : (
          <div className="mt-6 p-8 border border-border rounded-lg bg-background-weak text-center">
            <Text className="text-lg font-medium mb-2">
              No custom assistants yet
            </Text>
            <Text className="text-subtle mb-3">
              Create your first assistant to:
            </Text>
            <ul className="text-subtle text-sm list-disc text-left inline-block mb-3">
              <li>Build department-specific knowledge bases</li>
              <li>Create specialized research assistants</li>
              <li>Set up compliance and policy advisors</li>
            </ul>
            <Text className="text-subtle text-sm mb-4">
              ...and so much more!
            </Text>
            <CreateButton href="/assistants/new?admin=true">
              Create Your First Assistant
            </CreateButton>
            <div className="mt-6 pt-6 border-t border-border">
              <Text className="text-subtle text-sm">
                OR go{" "}
                <a
                  href="/admin/configuration/default-assistant"
                  className="text-link underline"
                >
                  here
                </a>{" "}
                to adjust the Default Assistant
              </Text>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Page() {
  const { personas, isLoading, error, refresh } = useAdminPersonas();

  return (
    <div className="mx-auto container">
      <AdminPageTitle icon={<AssistantsIcon size={32} />} title="Assistants" />

      {isLoading && <ThreeDotsLoader />}

      {error && (
        <ErrorCallout
          errorTitle="Failed to load assistants"
          errorMsg={
            error?.info?.message ||
            error?.info?.detail ||
            "An unknown error occurred"
          }
        />
      )}

      {!isLoading && !error && (
        <MainContent personas={personas} refreshPersonas={refresh} />
      )}
    </div>
  );
}
