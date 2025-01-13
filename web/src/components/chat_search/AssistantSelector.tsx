import React, {
  useState,
  useRef,
  useCallback,
  useEffect,
  useContext,
} from "react";
import { useAssistants } from "@/components/context/AssistantsContext";
import { useChatContext } from "@/components/context/ChatContext";
import { useUser } from "@/components/user/UserProvider";
import { Persona } from "@/app/admin/assistants/interfaces";
import { FiChevronDown } from "react-icons/fi";
import { destructureValue, getFinalLLM } from "@/lib/llm/utils";
import { updateModelOverrideForChatSession } from "@/app/chat/lib";
import { debounce } from "lodash";
import { LlmList } from "@/components/llm/LLMList";
import { checkPersonaRequiresImageGeneration } from "@/app/admin/assistants/lib";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { DraggableAssistantCard } from "@/components/assistants/AssistantCards";
import { updateUserAssistantList } from "@/lib/assistants/updateAssistantPreferences";

import Text from "@/components/ui/text";
import { getDisplayNameForModel, LlmOverrideManager } from "@/lib/hooks";
import { Tab } from "@headlessui/react";
import { AssistantIcon } from "../assistants/AssistantIcon";
import { restrictToVerticalAxis } from "@dnd-kit/modifiers";
import { restrictToParentElement } from "@dnd-kit/modifiers";
import { Drawer, DrawerContent, DrawerHeader, DrawerTitle } from "../ui/drawer";
import { truncateString } from "@/lib/utils";
import { SettingsContext } from "../settings/SettingsProvider";

const AssistantSelector = ({
  liveAssistant,
  onAssistantChange,
  chatSessionId,
  llmOverrideManager,
  isMobile,
}: {
  liveAssistant: Persona;
  onAssistantChange: (assistant: Persona) => void;
  chatSessionId?: string;
  llmOverrideManager: LlmOverrideManager;
  isMobile: boolean;
}) => {
  const { finalAssistants } = useAssistants();
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { llmProviders } = useChatContext();
  const { user } = useUser();

  const [assistants, setAssistants] = useState<Persona[]>(finalAssistants);
  const [isTemperatureExpanded, setIsTemperatureExpanded] = useState(false);

  // Initialize selectedTab from localStorage
  const [selectedTab, setSelectedTab] = useState<number>(() => {
    const storedTab = localStorage.getItem("assistantSelectorSelectedTab");
    return storedTab !== null ? Number(storedTab) : 0;
  });

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const handleDragEnd = async (event: DragEndEvent) => {
    const { active, over } = event;
    if (over && active.id !== over.id) {
      const oldIndex = assistants.findIndex(
        (item) => item.id.toString() === active.id
      );
      const newIndex = assistants.findIndex(
        (item) => item.id.toString() === over.id
      );
      const updatedAssistants = arrayMove(assistants, oldIndex, newIndex);
      setAssistants(updatedAssistants);
      await updateUserAssistantList(updatedAssistants.map((a) => a.id));
    }
  };

  // Handle tab change and update localStorage
  const handleTabChange = (index: number) => {
    setSelectedTab(index);
    localStorage.setItem("assistantSelectorSelectedTab", index.toString());
  };

  const settings = useContext(SettingsContext);

  // Get the user's default model
  const userDefaultModel = user?.preferences.default_model;

  const [_, currentLlm] = getFinalLLM(
    llmProviders,
    liveAssistant,
    llmOverrideManager.llmOverride ?? null
  );

  const requiresImageGeneration =
    checkPersonaRequiresImageGeneration(liveAssistant);

  const content = (
    <>
      <Tab.Group selectedIndex={selectedTab} onChange={handleTabChange}>
        <Tab.List className="flex p-1 space-x-1 bg-gray-100 rounded-t-md">
          <Tab
            className={({ selected }) =>
              `w-full py-2.5 text-sm leading-5 font-medium rounded-md
                 ${
                   selected
                     ? "bg-white text-gray-700 shadow"
                     : "text-gray-500 hover:bg-white/[0.12] hover:text-gray-700"
                 }`
            }
          >
            Assistant
          </Tab>
          <Tab
            className={({ selected }) =>
              `w-full py-2.5  text-sm leading-5 font-medium rounded-md
                 ${
                   selected
                     ? "bg-white text-gray-700 shadow"
                     : "text-gray-500 hover:bg-white/[0.12] hover:text-gray-700"
                 }`
            }
          >
            Model
          </Tab>
        </Tab.List>
        <Tab.Panels>
          <Tab.Panel className="p-3">
            <div className="mb-4">
              <h3 className="text-center text-lg font-semibold text-gray-800">
                Choose an Assistant
              </h3>
            </div>
            <DndContext
              sensors={sensors}
              collisionDetection={closestCenter}
              onDragEnd={handleDragEnd}
              modifiers={[restrictToVerticalAxis, restrictToParentElement]}
            >
              <SortableContext
                items={assistants.map((a) => a.id.toString())}
                strategy={verticalListSortingStrategy}
              >
                <div className="space-y-2 max-h-96 overflow-y-auto">
                  {assistants.map((assistant) => (
                    <DraggableAssistantCard
                      key={assistant.id.toString()}
                      assistant={assistant}
                      isSelected={liveAssistant.id === assistant.id}
                      onSelect={(assistant) => {
                        onAssistantChange(assistant);
                        setIsOpen(false);
                      }}
                      llmName={
                        assistant.llm_model_version_override ??
                        userDefaultModel ??
                        currentLlm
                      }
                    />
                  ))}
                </div>
              </SortableContext>
            </DndContext>
          </Tab.Panel>
          <Tab.Panel className="p-3">
            <div className="mb-4">
              <h3 className="text-center text-lg font-semibold text-gray-800 ">
                Choose a Model
              </h3>
            </div>
            <LlmList
              currentAssistant={liveAssistant}
              requiresImageGeneration={requiresImageGeneration}
              llmProviders={llmProviders}
              currentLlm={currentLlm}
              userDefault={userDefaultModel}
              onSelect={(value: string | null) => {
                if (value == null) return;
                const { modelName, name, provider } = destructureValue(value);
                llmOverrideManager.updateLLMOverride({
                  name,
                  provider,
                  modelName,
                });
                if (chatSessionId) {
                  updateModelOverrideForChatSession(chatSessionId, value);
                }
              }}
            />
            <div className="mt-4">
              <button
                className="flex items-center text-sm font-medium transition-colors duration-200"
                onClick={() => setIsTemperatureExpanded(!isTemperatureExpanded)}
              >
                <span className="mr-2 text-xs text-primary">
                  {isTemperatureExpanded ? "▼" : "►"}
                </span>
                <span>Temperature</span>
              </button>

              {isTemperatureExpanded && (
                <>
                  <Text className="mt-2 mb-8">
                    Adjust the temperature of the LLM. Higher temperatures will
                    make the LLM generate more creative and diverse responses,
                    while lower temperature will make the LLM generate more
                    conservative and focused responses.
                  </Text>

                  <div className="relative w-full">
                    <input
                      type="range"
                      onChange={(e) =>
                        llmOverrideManager.updateTemperature(
                          parseFloat(e.target.value)
                        )
                      }
                      className="w-full p-2 border border-border rounded-md"
                      min="0"
                      max="2"
                      step="0.01"
                      value={llmOverrideManager.temperature?.toString() || "0"}
                    />
                    <div
                      className="absolute text-sm"
                      style={{
                        left: `${(llmOverrideManager.temperature || 0) * 50}%`,
                        transform: `translateX(-${Math.min(
                          Math.max(
                            (llmOverrideManager.temperature || 0) * 50,
                            10
                          ),
                          90
                        )}%)`,
                        top: "-1.5rem",
                      }}
                    >
                      {llmOverrideManager.temperature}
                    </div>
                  </div>
                </>
              )}
            </div>
          </Tab.Panel>
        </Tab.Panels>
      </Tab.Group>
    </>
  );

  useEffect(() => {
    if (!isMobile) {
      const handleClickOutside = (event: MouseEvent) => {
        if (
          dropdownRef.current &&
          !dropdownRef.current.contains(event.target as Node)
        ) {
          setIsOpen(false);
        }
      };

      document.addEventListener("mousedown", handleClickOutside);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
      };
    }
  }, [isMobile]);

  return (
    <div className="pointer-events-auto relative" ref={dropdownRef}>
      <div
        className={`h-12 items-end flex justify-center 
          ${
            settings?.enterpriseSettings?.custom_header_content &&
            (settings?.enterpriseSettings?.two_lines_for_chat_header
              ? "mt-16 "
              : "mt-10")
          }
        `}
      >
        <div
          onClick={() => {
            setIsOpen(!isOpen);
            // Get selectedTab from localStorage when opening
            const storedTab = localStorage.getItem(
              "assistantSelectorSelectedTab"
            );
            setSelectedTab(storedTab !== null ? Number(storedTab) : 0);
          }}
          className="flex items-center gap-x-2 justify-between px-6 py-3 text-sm font-medium text-white bg-black rounded-full shadow-lg hover:shadow-xl transition-all duration-300 cursor-pointer"
        >
          <div className="h-4 flex gap-x-2 items-center">
            <AssistantIcon assistant={liveAssistant} size="xs" />
            <span className="font-bold">{liveAssistant.name}</span>
          </div>
          <div className="h-4 flex items-center">
            <span className="mr-2 text-xs">
              {truncateString(getDisplayNameForModel(currentLlm), 30)}
            </span>
            <FiChevronDown
              className={`w-3 h-3 text-white transition-transform duration-300 transform ${
                isOpen ? "rotate-180" : ""
              }`}
              aria-hidden="true"
            />
            <div className="invisible w-0">
              <AssistantIcon assistant={liveAssistant} size="xs" />
            </div>
          </div>
        </div>
      </div>

      {isMobile ? (
        <Drawer open={isOpen} onOpenChange={setIsOpen}>
          <DrawerContent>
            <DrawerHeader>
              <DrawerTitle>Assistant Selector</DrawerTitle>
            </DrawerHeader>
            {content}
          </DrawerContent>
        </Drawer>
      ) : (
        isOpen && (
          <div className="absolute z-10 w-96 mt-2 origin-top-center left-1/2 transform -translate-x-1/2 bg-white rounded-md shadow-lg ring-1 ring-black ring-opacity-5 focus:outline-none">
            {content}
          </div>
        )
      )}
    </div>
  );
};

export default AssistantSelector;
