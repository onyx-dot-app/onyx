"use client";

import React, { useMemo, useState } from "react";
import { Persona } from "@/app/admin/assistants/interfaces";
import { useRouter } from "next/navigation";

import { Modal } from "@/components/Modal";
import NewAssistantCard from "./AssistantCard";
import { useAssistants } from "@/components/context/AssistantsContext";

export const AssistantBadgeSelector = ({
  text,
  selected,
  toggleFilter,
}: {
  text: string;
  selected: boolean;
  toggleFilter: () => void;
}) => {
  return (
    <div
      className={`${
        selected
          ? "bg-neutral-900 text-white"
          : "bg-transparent text-neutral-900"
      } h-5 px-1 py-0.5 rounded-lg cursor-pointer text-[12px] font-normal leading-[10px] border border-black justify-center items-center gap-1 inline-flex`}
      onClick={toggleFilter}
    >
      {text}
    </div>
  );
};

export enum AssistantFilter {
  AdminCreated = "Admin-created",
  Pinned = "Pinned",
  Private = "Private",
  Public = "Public",
  Builtin = "Builtin",
}

const useAssistantFilter = () => {
  const [assistantFilters, setAssistantFilters] = useState<
    Record<AssistantFilter, boolean>
  >({
    [AssistantFilter.Builtin]: false,
    [AssistantFilter.AdminCreated]: false,
    [AssistantFilter.Pinned]: false,
    [AssistantFilter.Private]: false,
    [AssistantFilter.Public]: false,
  });

  const toggleAssistantFilter = (filter: AssistantFilter) => {
    setAssistantFilters((prevFilters) => ({
      ...prevFilters,
      [filter]: !prevFilters[filter],
    }));
  };

  return { assistantFilters, toggleAssistantFilter };
};

export default function AssistantModal({
  hideModal,
}: {
  hideModal: () => void;
}) {
  const { assistants, visibleAssistants, pinnedAssistants } = useAssistants();
  const { assistantFilters, toggleAssistantFilter } = useAssistantFilter();
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");

  const memoizedCurrentlyVisibleAssistants = useMemo(() => {
    return assistants.filter((assistant) => {
      const nameMatches = assistant.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const publicFilter =
        !assistantFilters[AssistantFilter.Public] || assistant.is_public;
      const privateFilter =
        !assistantFilters[AssistantFilter.Private] || !assistant.is_public;
      const pinnedFilter =
        !assistantFilters[AssistantFilter.Pinned] ||
        pinnedAssistants.map((a: Persona) => a.id).includes(assistant.id);
      const adminCreatedFilter =
        !assistantFilters[AssistantFilter.AdminCreated] ||
        assistant.is_default_persona;

      const builtinFilter =
        !assistantFilters[AssistantFilter.Builtin] || assistant.builtin_persona;

      return (
        nameMatches &&
        publicFilter &&
        privateFilter &&
        pinnedFilter &&
        adminCreatedFilter &&
        builtinFilter
      );
    });
  }, [assistants, searchQuery, assistantFilters, pinnedAssistants]);

  return (
    <Modal
      hideCloseButton
      onOutsideClick={hideModal}
      className="max-w-4xl  w-[95%] h-[80vh]"
    >
      <>
        <div className="flex justify-between items-center mb-0">
          <div className="h-10 px-4 w-full  rounded-lg flex-col justify-center items-start gap-2.5 inline-flex">
            <div className="h-16 rounded-md w-full shadow-[0px_0px_2px_0px_rgba(0,0,0,0.25)] border border-[#dcdad4] flex items-center px-3">
              <input
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                type="text"
                className="w-full h-full bg-transparent outline-none text-black"
              />
              <svg
                xmlns="http://www.w3.org/2000/svg"
                className="h-5 w-5 text-gray-400"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                />
              </svg>
            </div>
          </div>
          <button
            onClick={() => router.push("/assistants/new")}
            className="h-10 cursor-pointer px-6 py-3 bg-black rounded-md border border-black justify-center items-center gap-2.5 inline-flex"
          >
            <div className="text-[#fffcf4] text-lg font-normal leading-normal">
              Create
            </div>
          </button>
        </div>
        <div className="ml-4 flex py-2 items-center gap-x-2">
          <AssistantBadgeSelector
            text="Public"
            selected={assistantFilters[AssistantFilter.Public] ?? false}
            toggleFilter={() => toggleAssistantFilter(AssistantFilter.Public)}
          />
          <AssistantBadgeSelector
            text="Private"
            selected={assistantFilters[AssistantFilter.Private] ?? false}
            toggleFilter={() => toggleAssistantFilter(AssistantFilter.Private)}
          />
          <AssistantBadgeSelector
            text="Admin-Created"
            selected={assistantFilters[AssistantFilter.AdminCreated] ?? false}
            toggleFilter={() =>
              toggleAssistantFilter(AssistantFilter.AdminCreated)
            }
          />
          <AssistantBadgeSelector
            text="Pinned"
            selected={assistantFilters[AssistantFilter.Pinned] ?? false}
            toggleFilter={() => toggleAssistantFilter(AssistantFilter.Pinned)}
          />
          <AssistantBadgeSelector
            text="Builtin"
            selected={assistantFilters[AssistantFilter.Builtin] ?? false}
            toggleFilter={() => toggleAssistantFilter(AssistantFilter.Builtin)}
          />
        </div>

        <div className="w-full mt-2 justify-start h-fit px-2 grid grid-cols-1 md:grid-cols-2 gap-x-2 gap-y-3">
          {memoizedCurrentlyVisibleAssistants.map((assistant, index) => (
            <div key={index}>
              <NewAssistantCard
                pinned={pinnedAssistants.includes(assistant)}
                persona={assistant}
                closeModal={hideModal}
              />
            </div>
          ))}
        </div>
      </>
    </Modal>
  );
}
