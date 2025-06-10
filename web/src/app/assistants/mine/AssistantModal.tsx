"use client";

import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import AssistantCard from "./AssistantCard";
import { useAssistants } from "@/components/context/AssistantsContext";
import { useUser } from "@/components/user/UserProvider";
import { FilterIcon, XIcon } from "lucide-react";
import { checkUserOwnsAssistant } from "@/lib/assistants/checkOwnership";

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
      className={`
        select-none ${
          selected
            ? "bg-background-900 text-white"
            : "bg-transparent text-text-900"
        } w-12 h-5 text-center px-1 py-0.5 rounded-lg cursor-pointer text-[12px] font-normal leading-[10px] border border-black justify-center items-center gap-1 inline-flex`}
      onClick={toggleFilter}
    >
      {text}
    </div>
  );
};

export enum AssistantFilter {
  Pinned = "Pinned",
  Public = "Public",
  Private = "Private",
  Mine = "Mine",
}

const useAssistantFilter = () => {
  const [assistantFilters, setAssistantFilters] = useState<
    Record<AssistantFilter, boolean>
  >({
    [AssistantFilter.Pinned]: false,
    [AssistantFilter.Public]: false,
    [AssistantFilter.Private]: false,
    [AssistantFilter.Mine]: false,
  });

  const toggleAssistantFilter = (filter: AssistantFilter) => {
    setAssistantFilters((prevFilters) => ({
      ...prevFilters,
      [filter]: !prevFilters[filter],
    }));
  };

  return { assistantFilters, toggleAssistantFilter, setAssistantFilters };
};

interface AssistantModalProps {
  hideModal: () => void;
}

export function AssistantModal({ hideModal }: AssistantModalProps) {
  const { assistants, pinnedAssistants } = useAssistants();
  const { assistantFilters, toggleAssistantFilter } = useAssistantFilter();
  const router = useRouter();
  const { user } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [isSearchFocused, setIsSearchFocused] = useState(false);

  const memoizedCurrentlyVisibleAssistants = useMemo(() => {
    return assistants.filter((assistant) => {
      const nameMatches = assistant.name
        .toLowerCase()
        .includes(searchQuery.toLowerCase());
      const labelMatches = assistant.labels?.some((label) =>
        label.name.toLowerCase().includes(searchQuery.toLowerCase())
      );
      const publicFilter =
        !assistantFilters[AssistantFilter.Public] || assistant.is_public;
      const privateFilter =
        !assistantFilters[AssistantFilter.Private] || !assistant.is_public;
      const pinnedFilter =
        !assistantFilters[AssistantFilter.Pinned] ||
        (pinnedAssistants.map((a) => a.id).includes(assistant.id) ?? false);

      const mineFilter =
        !assistantFilters[AssistantFilter.Mine] ||
        checkUserOwnsAssistant(user, assistant);

      return (
        (nameMatches || labelMatches) &&
        publicFilter &&
        privateFilter &&
        pinnedFilter &&
        mineFilter
      );
    });
  }, [assistants, searchQuery, assistantFilters]);

  const featuredAssistants = [
    ...memoizedCurrentlyVisibleAssistants.filter(
      (assistant) => assistant.is_default_persona
    ),
  ];
  const allAssistants = memoizedCurrentlyVisibleAssistants.filter(
    (assistant) => !assistant.is_default_persona
  );

  return (
    <div
      onClick={hideModal}
      className="fixed inset-0 bg-neutral-950/80 bg-opacity-50 flex items-center justify-center z-50"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="p-0
          max-w-4xl
          overflow-hidden
          max-h-[80vh]
          w-[95%]
          bg-background
          rounded-md
          shadow-2xl
          transform
          transition-all
          duration-300
          ease-in-out
          relative
          w-11/12
          pt-10
          pb-10
          px-10
          flex
          flex-col"
        style={{
          position: "fixed",
          top: "10vh",
          left: "50%",
          transform: "translateX(-50%)",
          margin: 0,
        }}
        aria-label="Assistant Modal"
      >
        <div className="absolute top-2 right-2">
          <button
            onClick={hideModal}
            className="cursor-pointer text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-300 transition-colors duration-200 p-2"
            aria-label="Close modal"
          >
            <XIcon className="w-5 h-5" />
          </button>
        </div>
        <div className="flex overflow-hidden flex-col h-full">
          <div className="flex overflow-hidden flex-col h-full">
            <div className="flex flex-col sticky top-0 z-10">
              <div className="flex px-2 justify-between items-center gap-x-2 mb-0">
                <div className="h-12 w-full rounded-lg flex-col justify-center items-start gap-2.5 inline-flex">
                  <div className="h-12 rounded-md w-full shadow-[0px_0px_2px_0px_rgba(0,0,0,0.25)] border border-background-300 flex items-center px-3">
                    {!isSearchFocused && (
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        className="h-5 w-5 text-text-400"
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
                    )}
                    <input
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onFocus={() => setIsSearchFocused(true)}
                      onBlur={() => setIsSearchFocused(false)}
                      type="text"
                      className="w-full h-full bg-transparent outline-none text-black"
                    />
                  </div>
                </div>
                <button
                  onClick={() => router.push("/assistants/new")}
                  className="h-10 cursor-pointer px-6 py-3 bg-background-800 hover:bg-black rounded-md border border-black justify-center items-center gap-2.5 inline-flex"
                >
                  <div className="text-text-50 text-lg font-normal leading-normal">
                    Create
                  </div>
                </button>
              </div>
              <div className="px-2 flex py-4 items-center gap-x-2 flex-wrap">
                <FilterIcon className="text-text-800" size={16} />
                <AssistantBadgeSelector
                  text="Pinned"
                  selected={assistantFilters[AssistantFilter.Pinned]}
                  toggleFilter={() =>
                    toggleAssistantFilter(AssistantFilter.Pinned)
                  }
                />

                <AssistantBadgeSelector
                  text="Mine"
                  selected={assistantFilters[AssistantFilter.Mine]}
                  toggleFilter={() =>
                    toggleAssistantFilter(AssistantFilter.Mine)
                  }
                />
                <AssistantBadgeSelector
                  text="Private"
                  selected={assistantFilters[AssistantFilter.Private]}
                  toggleFilter={() =>
                    toggleAssistantFilter(AssistantFilter.Private)
                  }
                />
                <AssistantBadgeSelector
                  text="Public"
                  selected={assistantFilters[AssistantFilter.Public]}
                  toggleFilter={() =>
                    toggleAssistantFilter(AssistantFilter.Public)
                  }
                />
              </div>
              <div className="w-full border-t border-background-200" />
            </div>

            <div className="flex-grow overflow-y-auto">
              <h2 className="text-2xl font-semibold text-text-800 mb-2 px-4 py-2">
                Featured Assistants
              </h2>

              <div className="w-full px-2 pb-10 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-6">
                {featuredAssistants.length > 0 ? (
                  featuredAssistants.map((assistant, index) => (
                    <div key={index}>
                      <AssistantCard
                        pinned={pinnedAssistants
                          .map((a) => a.id)
                          .includes(assistant.id)}
                        persona={assistant}
                        closeModal={hideModal}
                      />
                    </div>
                  ))
                ) : (
                  <div className="col-span-2 text-center text-text-500">
                    No featured assistants match filters
                  </div>
                )}
              </div>

              {allAssistants && allAssistants.length > 0 && (
                <>
                  <h2 className="text-2xl font-semibold text-text-800 mt-4 mb-2 px-4 py-2">
                    All Assistants
                  </h2>

                  <div className="w-full mt-2 px-2 pb-2 grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-6">
                    {allAssistants
                      .sort((a, b) => b.id - a.id)
                      .map((assistant, index) => (
                        <div key={index}>
                          <AssistantCard
                            pinned={
                              user?.preferences?.pinned_assistants?.includes(
                                assistant.id
                              ) ?? false
                            }
                            persona={assistant}
                            closeModal={hideModal}
                          />
                        </div>
                      ))}
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
export default AssistantModal;
