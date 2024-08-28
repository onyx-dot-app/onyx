"use client";

import { Persona } from "@/app/admin/assistants/interfaces";
import { AssistantIcon } from "@/components/assistants/AssistantIcon";
import { User } from "@/lib/types";
import { Button } from "@tremor/react";
import Link from "next/link";
import { useState } from "react";
import { FiMinus, FiPlus, FiX } from "react-icons/fi";
import { NavigationButton } from "../NavigationButton";
import { AssistantsPageTitle } from "../AssistantsPageTitle";
import {
  addAssistantToList,
  removeAssistantFromList,
} from "@/lib/assistants/updateAssistantPreferences";
import { usePopup } from "@/components/admin/connectors/Popup";
import { useRouter } from "next/navigation";
import { AssistantTools, ToolsDisplay } from "../ToolsDisplay";

export function AssistantsGallery({
  assistants,
  user,
}: {
  assistants: Persona[];
  user: User | null;
}) {
  function filterAssistants(assistants: Persona[], query: string): Persona[] {
    return assistants.filter(
      (assistant) =>
        assistant.name.toLowerCase().includes(query.toLowerCase()) ||
        assistant.description.toLowerCase().includes(query.toLowerCase())
    );
  }

  const router = useRouter();

  const [searchQuery, setSearchQuery] = useState("");
  const { popup, setPopup } = usePopup();

  const allAssistantIds = assistants.map((assistant) => assistant.id);
  const filteredAssistants = filterAssistants(assistants, searchQuery);

  return (
    <>
      {popup}
      <div className="mx-auto w-searchbar-xs 2xl:w-searchbar-sm 3xl:w-searchbar">
        <AssistantsPageTitle>Assistant Gallery</AssistantsPageTitle>
        <div className="flex justify-center mb-6">
          <Link href="/assistants/mine">
            <NavigationButton>View Your Assistants</NavigationButton>
          </Link>
        </div>

        <p className="text-center mb-6">
          Discover and create custom assistants that combine instructions, extra
          knowledge, and any combination of tools.
        </p>

        <div className="mb-6">
          <input
            type="text"
            placeholder="Search assistants..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="
            w-full
            p-2
            border
            border-gray-300
            rounded
            focus:outline-none
            focus:ring-2
            focus:ring-blue-500
          "
          />
        </div>
        <div
          className="
          w-full
          grid
          grid-cols-2
          gap-4
          py-2
        "
        >
          {filteredAssistants.map((assistant) => (
            <div
              key={assistant.id}
              className="
              bg-background-emphasis
              rounded-lg
              shadow-md
              p-4
            "
            >
              <div className="flex items-center">
                <AssistantIcon assistant={assistant} />
                <h2
                  className="
                  text-xl
                  font-semibold
                  my-auto
                  ml-2
                  text-strong
                  line-clamp-2
                "
                >
                  {assistant.name}
                </h2>
                {user && (
                  <div className="ml-auto">
                    {!user.preferences?.chosen_assistants ||
                    user.preferences?.chosen_assistants?.includes(
                      assistant.id
                    ) ? (
                      <Button
                        className="
                          mr-2
                          my-auto
                        "
                        icon={FiMinus}
                        onClick={async () => {
                          if (
                            user.preferences?.chosen_assistants &&
                            user.preferences?.chosen_assistants.length === 1
                          ) {
                            setPopup({
                              message: `Cannot remove "${assistant.name}" - you must have at least one assistant.`,
                              type: "error",
                            });
                            return;
                          }

                          const success = await removeAssistantFromList(
                            assistant.id,
                            user.preferences?.chosen_assistants ||
                              allAssistantIds
                          );
                          if (success) {
                            setPopup({
                              message: `"${assistant.name}" has been removed from your list.`,
                              type: "success",
                            });
                            router.refresh();
                          } else {
                            setPopup({
                              message: `"${assistant.name}" could not be removed from your list.`,
                              type: "error",
                            });
                          }
                        }}
                        size="xs"
                        color="red"
                      >
                        Remove
                      </Button>
                    ) : (
                      <Button
                        className="
                      mr-2
                      my-auto
                    "
                        icon={FiPlus}
                        onClick={async () => {
                          const success = await addAssistantToList(
                            assistant.id,
                            user.preferences?.chosen_assistants ||
                              allAssistantIds
                          );
                          if (success) {
                            setPopup({
                              message: `"${assistant.name}" has been added to your list.`,
                              type: "success",
                            });
                            router.refresh();
                          } else {
                            setPopup({
                              message: `"${assistant.name}" could not be added to your list.`,
                              type: "error",
                            });
                          }
                        }}
                        size="xs"
                        color="green"
                      >
                        Add
                      </Button>
                    )}
                  </div>
                )}
              </div>

              <p className="text-sm mt-2">{assistant.description}</p>
              <p className="text-subtle text-sm my-2">
                Author: {assistant.owner?.email || "Danswer"}
              </p>
              {assistant.tools.length > 0 && (
                <AssistantTools list assistant={assistant} />
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
