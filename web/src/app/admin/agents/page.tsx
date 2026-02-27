"use client";

import { PersonasTable } from "./PersonaTable";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import Separator from "@/refresh-components/Separator";
import { AdminPageTitle } from "@/components/admin/Title";
import { SubLabel } from "@/components/Field";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { useAdminPersonas } from "@/hooks/useAdminPersonas";
import { Persona } from "./interfaces";
import { ThreeDotsLoader } from "@/components/Loading";
import { ErrorCallout } from "@/components/ErrorCallout";
import { SvgOnyxOctagon } from "@opal/icons";
import { useState, useEffect } from "react";
import Pagination from "@/refresh-components/Pagination";

const PAGE_SIZE = 20;

function MainContent({
  personas,
  totalItems,
  currentPage,
  onPageChange,
  refreshPersonas,
}: {
  personas: Persona[];
  totalItems: number;
  currentPage: number;
  onPageChange: (page: number) => void;
  refreshPersonas: () => void;
}) {
  // Filter out default/unified assistants.
  // NOTE: The backend should already exclude them if includeDefault = false is
  // provided. That change was made with the introduction of pagination; we keep
  // this filter here for now for backwards compatibility.
  const customPersonas = personas.filter((persona) => !persona.builtin_persona);
  const totalPages = Math.ceil(totalItems / PAGE_SIZE);

  // Clamp currentPage when totalItems shrinks (e.g., deleting the last item on a page)
  useEffect(() => {
    if (currentPage > totalPages && totalPages > 0) {
      onPageChange(totalPages);
    }
  }, [currentPage, totalPages, onPageChange]);

  return (
    <div>
      <Text className="mb-2">
        Agents are a way to build custom search/question-answering experiences
        for different use cases.
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

        <Title>Create an Agent</Title>
        <CreateButton href="/app/agents/create?admin=true">
          New Agent
        </CreateButton>

        <Separator />

        <Title>Existing Agents</Title>
        {totalItems > 0 ? (
          <>
            <SubLabel>
              Agents will be displayed as options on the Chat / Search
              interfaces in the order they are displayed below. Agents marked as
              hidden will not be displayed. Editable agents are shown at the
              top.
            </SubLabel>
            <PersonasTable
              personas={customPersonas}
              refreshPersonas={refreshPersonas}
              currentPage={currentPage}
              pageSize={PAGE_SIZE}
            />
            {totalPages > 1 && (
              <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={onPageChange}
              />
            )}
          </>
        ) : (
          <div className="mt-6 p-8 border border-border rounded-lg bg-background-weak text-center">
            <Text className="text-lg font-medium mb-2">
              No custom agents yet
            </Text>
            <Text className="text-subtle mb-3">
              Create your first agent to:
            </Text>
            <ul className="text-subtle text-sm list-disc text-left inline-block mb-3">
              <li>Build department-specific knowledge bases</li>
              <li>Create specialized research agents</li>
              <li>Set up compliance and policy advisors</li>
            </ul>
            <Text className="text-subtle text-sm mb-4">
              ...and so much more!
            </Text>
            <CreateButton href="/app/agents/create?admin=true">
              Create Your First Agent
            </CreateButton>
          </div>
        )}
      </div>
    </div>
  );
}

export default function Page() {
  const [currentPage, setCurrentPage] = useState(1);
  const { personas, totalItems, isLoading, error, refresh } = useAdminPersonas({
    pageNum: currentPage - 1, // Backend uses 0-indexed pages
    pageSize: PAGE_SIZE,
  });

  return (
    <>
      <AdminPageTitle icon={SvgOnyxOctagon} title="Agents" />

      {isLoading && <ThreeDotsLoader />}

      {error && (
        <ErrorCallout
          errorTitle="Failed to load agents"
          errorMsg={
            error?.info?.message ||
            error?.info?.detail ||
            "An unknown error occurred"
          }
        />
      )}

      {!isLoading && !error && (
        <MainContent
          personas={personas}
          totalItems={totalItems}
          currentPage={currentPage}
          onPageChange={setCurrentPage}
          refreshPersonas={refresh}
        />
      )}
    </>
  );
}
