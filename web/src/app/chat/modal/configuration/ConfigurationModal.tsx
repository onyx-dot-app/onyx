"use client";

import React, { useEffect } from "react";
import { Modal } from "../../../../components/Modal";
import { FilterManager, LlmOverrideManager } from "@/lib/hooks";
import { FiltersTab } from "./FiltersTab";
import { FiCpu, FiFilter, FiX } from "react-icons/fi";
import { IconType } from "react-icons";
import { FaBrain } from "react-icons/fa";
import { AssistantsTab } from "./AssistantsTab";
import { Persona } from "@/app/admin/assistants/interfaces";
import { LlmTab } from "./LlmTab";
import { LLMProviderDescriptor } from "@/app/admin/models/llm/interfaces";

const TabButton = ({
  label,
  icon: Icon,
  isActive,
  onClick,
}: {
  label: string;
  icon: IconType;
  isActive: boolean;
  onClick: () => void;
}) => (
  <button
    onClick={onClick}
    className={` 
      pb-4
      pt-6
      px-2
      text-emphasis 
      font-bold 
      ${isActive ? "border-b-2 border-accent" : ""} 
      hover:bg-hover-light 
      hover:text-strong 
      transition 
      duration-200 
      ease-in-out
      flex
    `}
  >
    <Icon className="inline-block mr-2 my-auto" size="16" />
    <p className="my-auto">{label}</p>
  </button>
);

export function ConfigurationModal({
  activeTab,
  setActiveTab,
  onClose,
  availableAssistants,
  selectedAssistant,
  setSelectedAssistant,
  filterManager,
  llmProviders,
  llmOverrideManager,
  chatSessionId,
}: {
  activeTab: string | null;
  setActiveTab: (tab: string | null) => void;
  onClose: () => void;
  availableAssistants: Persona[];
  selectedAssistant: Persona;
  setSelectedAssistant: (assistant: Persona) => void;
  filterManager: FilterManager;
  llmProviders: LLMProviderDescriptor[];
  llmOverrideManager: LlmOverrideManager;
  chatSessionId?: number;
}) {
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  if (!activeTab) return null;

  return (
    <Modal
      onOutsideClick={onClose}
      noPadding
      className="
        w-4/6 
        h-4/6
        flex
        flex-col
      "
    >
      <div className="rounded flex flex-col overflow-hidden">
        <div className="mb-4">
          <div className="flex border-b border-border bg-background-emphasis">
            <div className="flex px-6 gap-x-2">
              <TabButton
                label="Assistants"
                icon={FaBrain}
                isActive={activeTab === "assistants"}
                onClick={() => setActiveTab("assistants")}
              />
              <TabButton
                label="Models"
                icon={FiCpu}
                isActive={activeTab === "llms"}
                onClick={() => setActiveTab("llms")}
              />
              <TabButton
                label="Filters"
                icon={FiFilter}
                isActive={activeTab === "filters"}
                onClick={() => setActiveTab("filters")}
              />
            </div>
            <button
              className="
                ml-auto
                px-1
                py-1
                text-xs
                font-medium
                rounded
                hover:bg-hover
                focus:outline-none
                focus:ring-2
                focus:ring-offset-2
                focus:ring-subtle
                flex
                items-center
                h-fit
                my-auto
                mr-5
              "
              onClick={onClose}
            >
              <FiX size={24} />
            </button>
          </div>
        </div>

        <div className="flex flex-col overflow-y-auto">
          <div className="px-8 pt-4">
            {activeTab === "filters" && (
              <FiltersTab filterManager={filterManager} />
            )}

            {activeTab === "llms" && (
              <LlmTab
                chatSessionId={chatSessionId}
                llmOverrideManager={llmOverrideManager}
                currentAssistant={selectedAssistant}
              />
            )}

            {activeTab === "assistants" && (
              <div>
                <AssistantsTab
                  availableAssistants={availableAssistants}
                  llmProviders={llmProviders}
                  selectedAssistant={selectedAssistant}
                  onSelect={(assistant) => {
                    setSelectedAssistant(assistant);
                    onClose();
                  }}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}
